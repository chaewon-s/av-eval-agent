# -*- coding: utf-8 -*-
"""Record the visible CARLA desktop/window to an MP4 until a stop file appears."""

import argparse
import ctypes
import ctypes.wintypes
import os
import shutil
import time

import cv2
import numpy as np
from PIL import ImageGrab


def _find_window_rect(title_substring):
    if not title_substring:
        return None

    title_substring = title_substring.lower()
    user32 = ctypes.windll.user32
    rects = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_substring not in buffer.value.lower():
            return True

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width > 100 and height > 100:
            rects.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p)(callback)
    user32.EnumWindows(enum_proc, 0)
    return rects[0] if rects else None


def _resize_to_max_width(frame, max_width):
    if not max_width or frame.shape[1] <= max_width:
        return frame

    scale = float(max_width) / float(frame.shape[1])
    size = (max_width, int(frame.shape[0] * scale))
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def _cv2_output_path(output_path):
    abs_output_path = os.path.abspath(output_path)
    try:
        relative_path = os.path.relpath(abs_output_path, os.getcwd())
        if not relative_path.startswith('..') and not os.path.isabs(
                relative_path):
            return relative_path, None
    except ValueError:
        pass

    if all(ord(ch) < 128 for ch in output_path):
        return output_path, None

    temp_path = '_desktop_recording_%d.mp4' % os.getpid()
    return temp_path, abs_output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--stop-file', required=True)
    parser.add_argument('--fps', type=float, default=10.0)
    parser.add_argument('--max-seconds', type=float, default=180.0)
    parser.add_argument('--window-title', default='CARLA')
    parser.add_argument('--max-width', type=int, default=1920)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    if os.path.exists(args.stop_file):
        os.remove(args.stop_file)

    writer = None
    writer_output, final_output = _cv2_output_path(args.output)
    frame_size = None
    start_time = time.time()
    frame_period = 1.0 / max(args.fps, 1.0)
    bbox = None

    try:
        while not os.path.exists(args.stop_file):
            if time.time() - start_time >= args.max_seconds:
                break

            loop_start = time.time()
            bbox = bbox or _find_window_rect(args.window_title)
            image = ImageGrab.grab(bbox=bbox)
            frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            frame = _resize_to_max_width(frame, args.max_width)

            if writer is None:
                frame_size = (frame.shape[1], frame.shape[0])
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(
                    writer_output,
                    fourcc,
                    args.fps,
                    frame_size)

            if (frame.shape[1], frame.shape[0]) != frame_size:
                frame = cv2.resize(frame, frame_size)
            writer.write(frame)

            sleep_time = frame_period - (time.time() - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)
    finally:
        if writer is not None:
            writer.release()
        if final_output is not None and os.path.exists(writer_output):
            shutil.move(writer_output, final_output)


if __name__ == '__main__':
    main()
