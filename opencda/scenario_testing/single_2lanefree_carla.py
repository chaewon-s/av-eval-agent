# -*- coding: utf-8 -*-
"""
Scenario testing: Single vehicle dring in the customized 2 lane highway map.
"""
# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: TDG-Attribution-NonCommercial-NoDistrib

import os

import carla
import cv2
import numpy as np

import opencda.scenario_testing.utils.sim_api as sim_api
import opencda.scenario_testing.utils.customized_map_api as map_api

from opencda.core.common.cav_world import CavWorld
from opencda.scenario_testing.evaluations.evaluate_manager import \
    EvaluationManager
from opencda.scenario_testing.utils.yaml_utils import \
    add_current_time, save_yaml


class TopViewRecorder(object):
    """
    Save a real CARLA RGB camera from the same top-down transform as spectator.
    """

    def __init__(self, world, scenario_params):
        recorder_config = scenario_params.get('vehicle_base', {}).get(
            'topview_recording',
            {})
        self.enabled = recorder_config.get('enabled', False)
        self.sensor = None
        self.video_writer = None
        self.frame_count = 0
        self.save_frames = recorder_config.get('save_frames', True)

        if not self.enabled:
            return

        self.image_width = int(recorder_config.get('image_size_x', 1280))
        self.image_height = int(recorder_config.get('image_size_y', 720))
        self.height = float(recorder_config.get('height', 70.0))
        self.fps = float(recorder_config.get('fps', 10.0))

        current_path = os.path.dirname(os.path.realpath(__file__))
        datadump_config = scenario_params.get('vehicle_base', {}).get(
            'datadump',
            {})
        dump_title = datadump_config.get('title', 'scenario2')
        self.save_folder = os.path.abspath(os.path.join(
            current_path,
            '../../data_dumping',
            dump_title,
            scenario_params['current_time'],
            'topview_screen'))
        os.makedirs(self.save_folder, exist_ok=True)

        video_name = recorder_config.get('video_name', 'topview.mp4')
        self.video_path = os.path.join(self.save_folder, video_name)
        self.video_writer = cv2.VideoWriter(
            self.video_path,
            cv2.VideoWriter_fourcc(*'mp4v'),
            self.fps,
            (self.image_width, self.image_height))
        if not self.video_writer.isOpened():
            self.video_writer = None
            print('[TOPVIEW-RECORDER] warning: failed to open %s' %
                  self.video_path)

        blueprint = world.get_blueprint_library().find('sensor.camera.rgb')
        blueprint.set_attribute('image_size_x', str(self.image_width))
        blueprint.set_attribute('image_size_y', str(self.image_height))
        blueprint.set_attribute('fov', str(recorder_config.get('fov', 90)))
        if blueprint.has_attribute('sensor_tick'):
            blueprint.set_attribute(
                'sensor_tick',
                str(recorder_config.get('sensor_tick', 0.1)))

        spawn_transform = carla.Transform(
            carla.Location(z=self.height),
            carla.Rotation(pitch=-90))
        self.sensor = world.spawn_actor(blueprint, spawn_transform)
        self.sensor.listen(lambda image: self._save_image(image))
        print('[TOPVIEW-RECORDER] saving CARLA top-view video to %s' %
              self.video_path)

    def _save_image(self, image):
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        image_bgr = array[:, :, :3]
        self.frame_count += 1

        if self.video_writer is not None:
            self.video_writer.write(image_bgr)

        if self.save_frames:
            image_name = '%06d_topview.png' % self.frame_count
            cv2.imwrite(os.path.join(self.save_folder, image_name),
                        image_bgr)

    def set_transform(self, transform):
        if self.sensor is None:
            return

        self.sensor.set_transform(transform)

    def destroy(self):
        if self.sensor is not None:
            self.sensor.stop()
            self.sensor.destroy()
            self.sensor = None

        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None


def run_scenario(opt, scenario_params):
    scenario_manager = None
    eval_manager = None
    single_cav_list = []
    bg_veh_list = []
    topview_recorder = None
    recorder_started = False

    try:
        scenario_params = add_current_time(scenario_params)
        current_path = os.path.dirname(os.path.realpath(__file__))
        xodr_path = os.path.join(
            current_path,
            '../assets/2lane_freeway_simplified/2lane_freeway_simplified.xodr')

        # create CAV world
        cav_world = CavWorld(opt.apply_ml)
        # create scenario manager
        scenario_manager = sim_api.ScenarioManager(scenario_params,
                                                   opt.apply_ml,
                                                   opt.version,
                                                   xodr_path=xodr_path,
                                                   cav_world=cav_world)

        if opt.record:
            scenario_manager.client. \
                start_recorder("single_2lanefree_carla.log", True)

        single_cav_list = \
            scenario_manager.create_vehicle_manager(application=['single'],
                                                    data_dump=True,
                                                    map_helper=map_api.
                                                    spawn_helper_2lanefree)

        # create background traffic in carla
        traffic_manager, bg_veh_list = \
            scenario_manager.create_traffic_carla()

        # create evaluation manager
        eval_manager = \
            EvaluationManager(scenario_manager.cav_world,
                              script_name='single_2lanefree_carla',
                              current_time=scenario_params['current_time'])

        spectator = scenario_manager.world.get_spectator()
        topview_recorder = TopViewRecorder(scenario_manager.world,
                                           scenario_params)


        save_yaml_name = os.path.join(current_path,
                                      '../../data_dumping',
                                      scenario_params['vehicle_base']['datadump']['title'],
                                      scenario_params['current_time'], 
                                      'data_protocol.yaml')
        save_yaml(scenario_params, save_yaml_name)


        scenario_manager.client.start_recorder(f"../../../../OpenCDA/data_dumping/{scenario_params['vehicle_base']['datadump']['title']}/{scenario_params['current_time']}/scenario.log", True)
        recorder_started = True
        # run steps
        while True:
            scenario_manager.tick()
            transform = single_cav_list[0].vehicle.get_transform()
            spectator_transform = carla.Transform(
                transform.location +
                carla.Location(
                    z=70),
                carla.Rotation(
                    pitch=-
                    90))
            spectator.set_transform(spectator_transform)
            if topview_recorder is not None:
                topview_recorder.set_transform(spectator_transform)

            for i, single_cav in enumerate(single_cav_list):
                # print(single_cav.vehicle)
                single_cav.update_info()
                control = single_cav.run_step()
                single_cav.vehicle.apply_control(control)

    finally:
        if eval_manager is not None:
            eval_manager.evaluate()

        if topview_recorder is not None:
            topview_recorder.destroy()

        if scenario_manager is not None and (opt.record or recorder_started):
            scenario_manager.client.stop_recorder()

        if scenario_manager is not None:
            scenario_manager.close()

        for v in single_cav_list:
            v.destroy()
        for v in bg_veh_list:
            v.destroy()
