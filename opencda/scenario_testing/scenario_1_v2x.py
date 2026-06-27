# -*- coding: utf-8 -*-
"""
Scenario testing: merging vehicle joining a platoon in the
customized 2-lane freeway simplified map sorely with carla
"""
# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: TDG-Attribution-NonCommercial-NoDistrib
import os
import math

import carla
import cv2
import numpy as np

import opencda.scenario_testing.utils.sim_api as sim_api
from opencda.core.common.cav_world import CavWorld
from opencda.scenario_testing.evaluations.evaluate_manager import \
    EvaluationManager
from opencda.scenario_testing.utils.yaml_utils import add_current_time, save_yaml


V2X_DANGER_BRAKE = 0.65
OCCLUDER_HOLD_BRAKE = 1.0
COLLISION_STOP_BRAKE = 1.0
V2X_WARNING_PRINT_INTERVAL = 20
V2X_STOP_LINE_OFFSET_M = 11.0
V2X_STOP_LINE_HOLD_DISTANCE_M = 0.25
V2X_STOP_LINE_CREEP_DISTANCE_M = 0.6
V2X_STOP_LINE_APPROACH_DISTANCE_M = 12.0
NO_V2X_STOP_LINE_APPROACH_DISTANCE_M = 0.0
V2X_STOP_LINE_APPROACH_SPEED_KMH = 18.0
V2X_STOP_LINE_CREEP_SPEED_KMH = 5.0
V2X_STOP_LINE_APPROACH_THROTTLE = 0.65
V2X_STOP_LINE_NEAR_THROTTLE = 0.35
V2X_STOP_LINE_CREEP_THROTTLE = 0.10
V2X_STOP_LINE_COMFORT_DECEL_MPS2 = 1.4
V2X_STOP_LINE_BRAKE_GAIN = 0.06
V2X_STOP_LINE_MIN_BRAKE = 0.08
V2X_STOP_LINE_MAX_BRAKE = 0.38
V2X_STOP_LINE_THROTTLE_CAP = 0.18
V2X_STOP_LINE_STOP_SPEED_MPS = 0.25
EGO_SPEED_CAP_KMH = 20.0
EGO_SPEED_CAP_MARGIN_KMH = 0.8
EGO_ACCEL_LIMIT_MPS2 = 4.0
EGO_START_THROTTLE_CAP = 0.45
EGO_LOW_SPEED_THROTTLE_CAP = 0.55
EGO_CRUISE_THROTTLE_CAP = 0.65
V2X_RESTART_CLEARANCE_M = 7.0
V2X_RESTART_TTC_S = 3.0
V2X_RESTART_MIN_DISTANCE_M = 10.5
V2X_RESTART_THROTTLE = 0.35
V2X_RESTART_THROTTLE_INITIAL = 0.13
V2X_RESTART_THROTTLE_RAMP_STEP = 0.035
V2X_RESTART_RAMP_TICKS = 20
V2X_RESTART_ACCEL_LIMIT_MPS2 = 2.6
V2X_STOP_LINE_BRAKE_RISE_STEP = 0.040
V2X_STOP_LINE_BRAKE_FALL_STEP = 0.060
SCRIPTED_ACTOR_SPEED_KMH = 20.0
SCRIPTED_ACTOR_START_ACCEL_MPS2 = 1.8
SCRIPTED_ACTOR_DECEL_MPS2 = 5.0
SCRIPTED_ACTOR_DECEL_START_X = 306.0
SCRIPTED_ACTOR_MIN_SPEED_KMH = 20.0
SCRIPTED_ACTOR_LATERAL_SPEED_MPS = 1.7
SCRIPTED_ACTOR_LANE_TOLERANCE_M = 0.15
HUMAN_VISUAL_REACTION_RANGE_M = 5.0
HUMAN_OCCLUSION_MARGIN_M = 0.5
HUMAN_REACTION_BRAKE_TICKS = 1000
HUMAN_EMERGENCY_BRAKE = 1.0
HUMAN_EMERGENCY_DECEL_MPS2 = 8.0
HUMAN_EMERGENCY_STOP_SPEED_KMH = 0.0
DEFAULT_SCENARIO_MAX_TICKS = 90


class TopViewRecorder(object):
    """
    Save a CARLA RGB camera that follows the spectator top-down transform.
    """

    def __init__(self, world, scenario_params):
        recorder_config = scenario_params.get('vehicle_base', {}).get(
            'topview_recording',
            {})
        self.enabled = recorder_config.get('enabled', False)
        self.sensor = None
        self.frame_count = 0

        if not self.enabled:
            return

        self.image_width = int(recorder_config.get('image_size_x', 1280))
        self.image_height = int(recorder_config.get('image_size_y', 720))
        self.height = float(recorder_config.get('height', 70.0))

        current_path = os.path.dirname(os.path.realpath(__file__))
        datadump_config = scenario_params.get('vehicle_base', {}).get(
            'datadump',
            {})
        self.relative_save_folder = os.path.join(
            'data_dumping',
            datadump_config.get('title', 'scenario1'),
            scenario_params['current_time'],
            'topview_screen')
        self.save_folder = os.path.join(
            current_path,
            '../../data_dumping',
            datadump_config.get('title', 'scenario1'),
            scenario_params['current_time'],
            'topview_screen')
        os.makedirs(self.save_folder, exist_ok=True)
        os.makedirs(self.relative_save_folder, exist_ok=True)

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
        print('[TOPVIEW-RECORDER] saving CARLA top-view RGB frames to %s' %
              self.save_folder)

    def _save_image(self, image):
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        image_bgr = array[:, :, :3]
        self.frame_count += 1
        image_name = '%06d_topview.png' % self.frame_count
        cv2.imwrite(os.path.join(self.relative_save_folder, image_name),
                    image_bgr)

    def set_transform(self, transform):
        if self.sensor is None:
            return

        self.sensor.set_transform(transform)

    def destroy(self):
        if self.sensor is None:
            return

        self.sensor.stop()
        self.sensor.destroy()
        self.sensor = None


def _get_cav_names(scenario_params, cav_count):
    cav_configs = scenario_params.get('scenario', {}).get('single_cav_list', [])
    cav_names = []

    for i in range(cav_count):
        if i < len(cav_configs):
            cav_names.append(cav_configs[i].get('name', 'cav_%d' % i))
        else:
            cav_names.append('cav_%d' % i)

    return cav_names


def _get_cav_index(cav_names, preferred_names, fallback_index=None):
    for i, cav_name in enumerate(cav_names):
        if cav_name in preferred_names:
            return i

    if fallback_index is not None and len(cav_names) > fallback_index:
        return fallback_index

    return None


def _get_v2x_range(cav_manager):
    v2x_manager = getattr(cav_manager, 'v2x_manager', None)
    communication_range = getattr(v2x_manager, 'communication_range', 30.0)

    try:
        return float(communication_range)
    except (TypeError, ValueError):
        return 30.0


def _is_v2x_enabled(cav_manager):
    v2x_manager = getattr(cav_manager, 'v2x_manager', None)
    return bool(getattr(v2x_manager, 'cda_enabled', True))


def _normalize_xy(vector):
    norm = math.sqrt(vector.x * vector.x + vector.y * vector.y)
    if norm < 0.001:
        return carla.Vector3D(x=1.0, y=0.0, z=0.0)
    return carla.Vector3D(x=vector.x / norm, y=vector.y / norm, z=0.0)


def _get_vehicle_speed_mps(vehicle):
    velocity = vehicle.get_velocity()
    return math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)


def _get_route_forward(cav_manager):
    scripted_forward = getattr(cav_manager, '_scripted_actor_forward', None)
    if scripted_forward is not None:
        return _normalize_xy(scripted_forward)

    agent = getattr(cav_manager, 'agent', None)
    start_waypoint = getattr(agent, 'start_waypoint', None)
    end_waypoint = getattr(agent, 'end_waypoint', None)
    if start_waypoint is not None and end_waypoint is not None:
        start_location = start_waypoint.transform.location
        end_location = end_waypoint.transform.location
        return _normalize_xy(carla.Vector3D(
            x=end_location.x - start_location.x,
            y=end_location.y - start_location.y,
            z=0.0))

    return _normalize_xy(cav_manager.vehicle.get_transform().get_forward_vector())


def _get_route_origin(cav_manager):
    scripted_origin = getattr(cav_manager, '_scripted_actor_path_origin', None)
    if scripted_origin is not None:
        return scripted_origin

    agent = getattr(cav_manager, 'agent', None)
    start_waypoint = getattr(agent, 'start_waypoint', None)
    if start_waypoint is not None:
        return start_waypoint.transform.location

    return cav_manager.vehicle.get_location()


def _path_intersection_2d(origin_a, forward_a, origin_b, forward_b):
    denominator = forward_a.x * forward_b.y - forward_a.y * forward_b.x
    if abs(denominator) < 0.001:
        return None

    delta_x = origin_b.x - origin_a.x
    delta_y = origin_b.y - origin_a.y
    distance_a = (
        delta_x * forward_b.y - delta_y * forward_b.x) / denominator

    return carla.Location(
        x=origin_a.x + forward_a.x * distance_a,
        y=origin_a.y + forward_a.y * distance_a,
        z=origin_a.z)


def _get_stop_line_state(receiver_manager, actor_manager):
    stop_line_location = getattr(receiver_manager,
                                 '_v2x_stop_line_location',
                                 None)
    stop_line_forward = getattr(receiver_manager,
                                '_v2x_stop_line_forward',
                                None)
    if stop_line_location is not None and stop_line_forward is not None:
        return stop_line_location, stop_line_forward

    receiver_forward = _get_route_forward(receiver_manager)
    actor_forward = _get_route_forward(actor_manager)
    conflict_location = _path_intersection_2d(
        _get_route_origin(receiver_manager),
        receiver_forward,
        _get_route_origin(actor_manager),
        actor_forward)
    if conflict_location is None:
        conflict_location = actor_manager.vehicle.get_location()
    receiver_manager._v2x_conflict_location = conflict_location

    stop_line_location = carla.Location(
        x=conflict_location.x - receiver_forward.x * V2X_STOP_LINE_OFFSET_M,
        y=conflict_location.y - receiver_forward.y * V2X_STOP_LINE_OFFSET_M,
        z=conflict_location.z)
    receiver_manager._v2x_stop_line_location = stop_line_location
    receiver_manager._v2x_stop_line_forward = receiver_forward

    return stop_line_location, receiver_forward


def _get_conflict_location(receiver_manager, actor_manager):
    conflict_location = getattr(receiver_manager,
                                '_v2x_conflict_location',
                                None)
    if conflict_location is not None:
        return conflict_location

    stop_line_location, stop_line_forward = _get_stop_line_state(
        receiver_manager,
        actor_manager)
    conflict_location = carla.Location(
        x=stop_line_location.x + stop_line_forward.x * V2X_STOP_LINE_OFFSET_M,
        y=stop_line_location.y + stop_line_forward.y * V2X_STOP_LINE_OFFSET_M,
        z=stop_line_location.z)
    receiver_manager._v2x_conflict_location = conflict_location

    return conflict_location


def _distance_to_stop_line(receiver_manager, actor_manager):
    stop_line_location, stop_line_forward = _get_stop_line_state(
        receiver_manager,
        actor_manager)
    vehicle_location = receiver_manager.vehicle.get_location()
    return (
        (stop_line_location.x - vehicle_location.x) * stop_line_forward.x +
        (stop_line_location.y - vehicle_location.y) * stop_line_forward.y)


def _hold_at_stop_line(control, receiver_manager):
    receiver_manager.vehicle.set_target_velocity(
        carla.Vector3D(0.0, 0.0, 0.0))
    return carla.VehicleControl(throttle=0.0,
                                steer=control.steer,
                                brake=V2X_DANGER_BRAKE,
                                hand_brake=False)


def _vehicle_radius(vehicle):
    extent = vehicle.bounding_box.extent
    return math.sqrt(extent.x * extent.x + extent.y * extent.y)


def _calculate_ttc(receiver_manager, actor_manager):
    receiver_location = receiver_manager.vehicle.get_location()
    actor_location = actor_manager.vehicle.get_location()
    receiver_velocity = receiver_manager.vehicle.get_velocity()
    actor_velocity = actor_manager.vehicle.get_velocity()
    relative_x = actor_location.x - receiver_location.x
    relative_y = actor_location.y - receiver_location.y
    relative_vx = actor_velocity.x - receiver_velocity.x
    relative_vy = actor_velocity.y - receiver_velocity.y
    center_distance = max(
        math.sqrt(relative_x * relative_x + relative_y * relative_y),
        1e-6)
    clearance = center_distance - (
        _vehicle_radius(receiver_manager.vehicle) +
        _vehicle_radius(actor_manager.vehicle))
    if clearance <= 0.0:
        return 0.0

    closing_rate = -(
        relative_x * relative_vx + relative_y * relative_vy) / center_distance
    if closing_rate <= 1e-3:
        return None

    return clearance / closing_rate


def _is_v2x_restart_safe(receiver_manager, actor_manager):
    conflict_location = _get_conflict_location(receiver_manager,
                                               actor_manager)
    actor_forward = _get_route_forward(actor_manager)
    actor_location = actor_manager.vehicle.get_location()
    actor_clearance = (
        (actor_location.x - conflict_location.x) * actor_forward.x +
        (actor_location.y - conflict_location.y) * actor_forward.y)
    if actor_clearance < V2X_RESTART_CLEARANCE_M:
        return False, actor_clearance, _calculate_ttc(receiver_manager,
                                                      actor_manager)

    center_distance = receiver_manager.vehicle.get_location().distance(
        actor_location)
    ttc = _calculate_ttc(receiver_manager, actor_manager)
    ttc_safe = ttc is None or ttc >= V2X_RESTART_TTC_S
    distance_safe = center_distance >= V2X_RESTART_MIN_DISTANCE_M

    return ttc_safe and distance_safe, actor_clearance, ttc


def _rate_limit_value(value, previous, rise_step, fall_step=None):
    if previous is None:
        return value
    if fall_step is None:
        fall_step = rise_step
    if value > previous + rise_step:
        return previous + rise_step
    if value < previous - fall_step:
        return previous - fall_step
    return value


def _smooth_v2x_stop_line_brake(receiver_manager, brake):
    previous = getattr(receiver_manager, '_v2x_stop_line_last_brake', None)
    smoothed = _rate_limit_value(
        brake,
        previous,
        V2X_STOP_LINE_BRAKE_RISE_STEP,
        V2X_STOP_LINE_BRAKE_FALL_STEP)
    receiver_manager._v2x_stop_line_last_brake = smoothed
    return smoothed


def _restart_from_stop_line(control, receiver_manager):
    receiver_manager._v2x_stop_line_active = False
    receiver_manager._v2x_stop_line_waiting = False
    receiver_manager._v2x_stop_line_released = True
    receiver_manager._v2x_restart_ramp_ticks = 0
    receiver_manager._v2x_stop_line_last_brake = 0.0
    control.hand_brake = False
    control.brake = 0.0
    control.throttle = min(
        max(control.throttle, V2X_RESTART_THROTTLE_INITIAL),
        V2X_RESTART_THROTTLE_INITIAL)
    return control


def _apply_v2x_restart_ramp(control, cav_manager):
    if not getattr(cav_manager, '_v2x_stop_line_released', False):
        return control

    ramp_tick = getattr(cav_manager, '_v2x_restart_ramp_ticks', None)
    if ramp_tick is None:
        return control
    if ramp_tick >= V2X_RESTART_RAMP_TICKS:
        delattr(cav_manager, '_v2x_restart_ramp_ticks')
        return control

    throttle_cap = min(
        V2X_RESTART_THROTTLE,
        V2X_RESTART_THROTTLE_INITIAL +
        ramp_tick * V2X_RESTART_THROTTLE_RAMP_STEP)
    if control.brake <= 0.01 and not control.hand_brake:
        control.throttle = min(control.throttle, throttle_cap)
    cav_manager._v2x_restart_ramp_ticks = ramp_tick + 1
    return control


def _apply_ego_speed_cap(control, cav_manager):
    speed_kmh = _get_vehicle_speed_mps(cav_manager.vehicle) * 3.6
    if speed_kmh >= EGO_SPEED_CAP_KMH - 1.0:
        control.throttle = min(control.throttle, 0.08)

    overspeed_kmh = speed_kmh - EGO_SPEED_CAP_KMH
    if overspeed_kmh <= EGO_SPEED_CAP_MARGIN_KMH:
        return control

    control.throttle = 0.0
    brake = 0.14 + overspeed_kmh * 0.045
    control.brake = max(control.brake, min(0.35, brake))
    return control


def _apply_ego_acceleration_smoothing(control, cav_manager):
    speed_mps = _get_vehicle_speed_mps(cav_manager.vehicle)
    speed_kmh = speed_mps * 3.6
    world = cav_manager.vehicle.get_world()
    dt = world.get_settings().fixed_delta_seconds or 0.1
    last_speed_mps = getattr(cav_manager, '_ego_last_speed_mps', None)
    cav_manager._ego_last_speed_mps = speed_mps

    if _is_v2x_enabled(cav_manager):
        control = _apply_v2x_restart_ramp(control, cav_manager)

    if control.brake > 0.01 or control.hand_brake:
        return control

    if speed_kmh < 3.0:
        control.throttle = min(control.throttle, EGO_START_THROTTLE_CAP)
    elif speed_kmh < 10.0:
        control.throttle = min(control.throttle, EGO_LOW_SPEED_THROTTLE_CAP)
    elif speed_kmh < EGO_SPEED_CAP_KMH - 1.0:
        control.throttle = min(control.throttle, EGO_CRUISE_THROTTLE_CAP)

    if last_speed_mps is None:
        return control

    accel_mps2 = (speed_mps - last_speed_mps) / max(dt, 0.001)
    accel_limit_mps2 = EGO_ACCEL_LIMIT_MPS2
    if (getattr(cav_manager, '_v2x_restart_ramp_ticks', None) is not None and
            _is_v2x_enabled(cav_manager)):
        accel_limit_mps2 = min(accel_limit_mps2, V2X_RESTART_ACCEL_LIMIT_MPS2)
    if accel_mps2 > accel_limit_mps2:
        control.throttle = min(control.throttle, 0.20)

    return control


def _ignore_unseen_no_v2x_hazard_brake(control,
                                       receiver_manager,
                                       actor_manager):
    if (_is_v2x_enabled(receiver_manager) and
            _is_v2x_enabled(actor_manager)):
        return control

    if getattr(receiver_manager, '_human_visual_reaction_active', False):
        return control

    if control.brake <= 0.01 and control.throttle > 0.01:
        return control

    speed_kmh = _get_vehicle_speed_mps(receiver_manager.vehicle) * 3.6
    if speed_kmh >= EGO_SPEED_CAP_KMH - 1.0:
        return control

    if not getattr(receiver_manager,
                   '_no_v2x_unseen_hazard_override_reported',
                   False):
        print('[NO-V2X] unseen default hazard brake ignored before visual detection')
        receiver_manager._no_v2x_unseen_hazard_override_reported = True

    control.hand_brake = False
    control.brake = 0.0
    if speed_kmh < 3.0:
        control.throttle = max(control.throttle, EGO_START_THROTTLE_CAP)
    elif speed_kmh < 10.0:
        control.throttle = max(control.throttle, EGO_LOW_SPEED_THROTTLE_CAP)
    else:
        control.throttle = max(control.throttle, EGO_CRUISE_THROTTLE_CAP)
    return control


def _get_stop_line_approach_target_mps(
        distance_to_stop,
        approach_distance=V2X_STOP_LINE_APPROACH_DISTANCE_M):
    if distance_to_stop <= V2X_STOP_LINE_CREEP_DISTANCE_M:
        return V2X_STOP_LINE_CREEP_SPEED_KMH / 3.6

    if distance_to_stop <= approach_distance:
        span = approach_distance - V2X_STOP_LINE_CREEP_DISTANCE_M
        ratio = (
            distance_to_stop - V2X_STOP_LINE_CREEP_DISTANCE_M) / span
        target_kmh = V2X_STOP_LINE_CREEP_SPEED_KMH + ratio * (
            V2X_STOP_LINE_APPROACH_SPEED_KMH -
            V2X_STOP_LINE_CREEP_SPEED_KMH)
        return target_kmh / 3.6

    return None


def _get_stop_line_roll_throttle(distance_to_stop):
    if distance_to_stop <= V2X_STOP_LINE_HOLD_DISTANCE_M:
        return 0.0
    if distance_to_stop <= V2X_STOP_LINE_CREEP_DISTANCE_M:
        return V2X_STOP_LINE_CREEP_THROTTLE
    if distance_to_stop <= 12.0:
        return V2X_STOP_LINE_NEAR_THROTTLE
    return V2X_STOP_LINE_APPROACH_THROTTLE


def _apply_stop_line_control(control, receiver_manager, distance_to_stop):
    speed_mps = _get_vehicle_speed_mps(receiver_manager.vehicle)
    if (distance_to_stop <= V2X_STOP_LINE_HOLD_DISTANCE_M or
            (distance_to_stop <= V2X_STOP_LINE_CREEP_DISTANCE_M and
             speed_mps <= V2X_STOP_LINE_STOP_SPEED_MPS)):
        receiver_manager._v2x_stop_line_waiting = True
        return _hold_at_stop_line(control, receiver_manager), 0.0, True

    stop_distance = max(
        distance_to_stop - V2X_STOP_LINE_HOLD_DISTANCE_M,
        0.1)
    target_speed_mps = math.sqrt(
        2.0 * V2X_STOP_LINE_COMFORT_DECEL_MPS2 * stop_distance)

    approach_target_mps = _get_stop_line_approach_target_mps(
        distance_to_stop)
    if approach_target_mps is not None:
        target_speed_mps = min(target_speed_mps, approach_target_mps)

    if distance_to_stop <= V2X_STOP_LINE_CREEP_DISTANCE_M:
        target_speed_mps = min(target_speed_mps, 1.2)

    speed_error_mps = speed_mps - target_speed_mps
    control.throttle = min(control.throttle, V2X_STOP_LINE_THROTTLE_CAP)

    if speed_error_mps > 0.15:
        required_decel = speed_mps * speed_mps / (2.0 * stop_distance)
        brake = required_decel * V2X_STOP_LINE_BRAKE_GAIN
        brake += speed_error_mps * 0.08
        brake = max(V2X_STOP_LINE_MIN_BRAKE,
                    min(V2X_STOP_LINE_MAX_BRAKE, brake))
        if distance_to_stop <= V2X_STOP_LINE_APPROACH_DISTANCE_M:
            brake = max(brake, 0.12)
        if distance_to_stop <= 3.0:
            brake = max(brake, 0.16)
        if distance_to_stop <= 1.5:
            brake = max(brake, 0.22)
        if distance_to_stop <= V2X_STOP_LINE_CREEP_DISTANCE_M:
            brake = max(brake, 0.24)
        brake = _smooth_v2x_stop_line_brake(receiver_manager, brake)
        control.throttle = 0.0
        control.brake = max(control.brake, brake)
    elif (distance_to_stop <= V2X_STOP_LINE_APPROACH_DISTANCE_M and
          speed_mps < target_speed_mps - 0.25):
        control.brake = 0.0
        control.hand_brake = False
        control.throttle = max(
            control.throttle,
            _get_stop_line_roll_throttle(distance_to_stop))

    return control, target_speed_mps * 3.6, False


def _has_collision(cav_manager):
    safety_manager = getattr(cav_manager, 'safety_manager', None)
    sensors = getattr(safety_manager, 'sensors', [])

    for sensor in sensors:
        status = sensor.return_status()
        if status.get('collision', False):
            return True

    return False


def _hold_after_collision(cav_manager):
    cav_manager.vehicle.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
    cav_manager.vehicle.apply_control(
        carla.VehicleControl(throttle=0.0,
                             brake=COLLISION_STOP_BRAKE,
                             hand_brake=True))


def _vehicle_local_xy(location, vehicle_transform):
    yaw = math.radians(vehicle_transform.rotation.yaw)
    delta_x = location.x - vehicle_transform.location.x
    delta_y = location.y - vehicle_transform.location.y
    forward_x = math.cos(yaw)
    forward_y = math.sin(yaw)
    right_x = -math.sin(yaw)
    right_y = math.cos(yaw)

    return (
        delta_x * forward_x + delta_y * forward_y,
        delta_x * right_x + delta_y * right_y)


def _segment_intersects_axis_box(start_xy, end_xy, half_x, half_y):
    start_x, start_y = start_xy
    end_x, end_y = end_xy
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    t_min = 0.0
    t_max = 1.0

    for start, delta, half_size in (
            (start_x, delta_x, half_x),
            (start_y, delta_y, half_y)):
        if abs(delta) < 1e-6:
            if abs(start) > half_size:
                return False
            continue

        t1 = (-half_size - start) / delta
        t2 = (half_size - start) / delta
        near = min(t1, t2)
        far = max(t1, t2)
        t_min = max(t_min, near)
        t_max = min(t_max, far)
        if t_min > t_max:
            return False

    return True


def _is_line_of_sight_blocked(observer_manager,
                              target_manager,
                              occluder_manager):
    if occluder_manager is None:
        return False

    observer_location = observer_manager.vehicle.get_location()
    target_location = target_manager.vehicle.get_location()
    occluder_transform = occluder_manager.vehicle.get_transform()
    extent = occluder_manager.vehicle.bounding_box.extent
    start_xy = _vehicle_local_xy(observer_location, occluder_transform)
    end_xy = _vehicle_local_xy(target_location, occluder_transform)

    return _segment_intersects_axis_box(
        start_xy,
        end_xy,
        extent.x + HUMAN_OCCLUSION_MARGIN_M,
        extent.y + HUMAN_OCCLUSION_MARGIN_M)


def _apply_human_emergency_control(control):
    control.throttle = 0.0
    control.brake = max(control.brake, HUMAN_EMERGENCY_BRAKE)
    return control


def _is_human_reaction_brake_active(cav_manager, tick_count):
    reaction_tick = getattr(cav_manager,
                            '_human_visual_reaction_tick',
                            None)
    if reaction_tick is None:
        return False

    return True


def _apply_human_visual_reaction_if_needed(ego_manager,
                                           actor_manager,
                                           occluder_manager,
                                           ego_name,
                                           actor_name,
                                           tick_count):
    if (_is_v2x_enabled(ego_manager) and
            _is_v2x_enabled(actor_manager)):
        return False

    if getattr(ego_manager, '_human_visual_reaction_active', False):
        brake_active = _is_human_reaction_brake_active(ego_manager,
                                                       tick_count)
        if (not brake_active and
                not getattr(ego_manager,
                            '_human_visual_reaction_release_reported',
                            False)):
            print('[HUMAN-REACTION] %s released brief brake pulse on tick %d; continuing naturally' %
                  (ego_name, tick_count))
            ego_manager._human_visual_reaction_release_reported = True
        return brake_active

    distance = ego_manager.vehicle.get_location().distance(
        actor_manager.vehicle.get_location())
    if distance > HUMAN_VISUAL_REACTION_RANGE_M:
        return False

    if _is_line_of_sight_blocked(ego_manager,
                                 actor_manager,
                                 occluder_manager):
        return False

    ego_manager._human_visual_reaction_active = True
    actor_manager._human_visual_reaction_active = True
    ego_manager._human_visual_reaction_tick = tick_count
    actor_manager._human_visual_reaction_tick = tick_count
    print('[HUMAN-REACTION] %s visually detected %s at %.2fm on tick %d; panic full brake activated (SCREECH)' %
          (ego_name, actor_name, distance, tick_count))
    return True


def _dump_vehicle_data(cav_manager):
    data_dumper = getattr(cav_manager, 'data_dumper', None)
    if data_dumper is None:
        return

    data_dumper.run_step(cav_manager.perception_manager,
                         cav_manager.localizer,
                         cav_manager.agent)


def _apply_scripted_actor_motion(actor_manager,
                                 speed_kmh=SCRIPTED_ACTOR_SPEED_KMH,
                                 tick_count=None):
    vehicle = actor_manager.vehicle
    transform = vehicle.get_transform()
    world = vehicle.get_world()
    agent = getattr(actor_manager, 'agent', None)
    end_waypoint = getattr(agent, 'end_waypoint', None)

    if not hasattr(actor_manager, '_scripted_actor_path_origin'):
        origin = transform.location
        if end_waypoint is not None:
            destination = end_waypoint.transform.location
        else:
            forward = transform.get_forward_vector()
            destination = carla.Location(
                x=origin.x + forward.x * 100.0,
                y=origin.y + forward.y * 100.0,
                z=origin.z)

        path_x = destination.x - origin.x
        path_y = destination.y - origin.y
        path_norm = math.sqrt(path_x * path_x + path_y * path_y)
        if path_norm < 0.001:
            initial_forward = transform.get_forward_vector()
            path_x = initial_forward.x
            path_y = initial_forward.y
            path_norm = math.sqrt(path_x * path_x + path_y * path_y)

        actor_manager._scripted_actor_path_origin = carla.Location(
            x=origin.x,
            y=origin.y,
            z=origin.z)
        actor_manager._scripted_actor_forward = carla.Vector3D(
            x=path_x / path_norm,
            y=path_y / path_norm,
            z=0.0)

    fixed_delta_seconds = world.get_settings().fixed_delta_seconds
    dt = fixed_delta_seconds if fixed_delta_seconds else 0.05
    current_speed_kmh = getattr(actor_manager,
                                '_scripted_actor_speed_kmh',
                                0.0)

    human_brake_active = _is_human_reaction_brake_active(actor_manager,
                                                         tick_count)

    if current_speed_kmh < speed_kmh and not human_brake_active:
        if not getattr(actor_manager,
                       '_scripted_actor_accel_reported',
                       False):
            print('[SCRIPTED-ACTOR-ACCEL] subject startup accel capped at %.1f m/s^2 toward %.1f km/h' %
                  (SCRIPTED_ACTOR_START_ACCEL_MPS2, speed_kmh))
            actor_manager._scripted_actor_accel_reported = True
        current_speed_kmh = min(
            speed_kmh,
            current_speed_kmh +
            SCRIPTED_ACTOR_START_ACCEL_MPS2 * dt * 3.6)

    if transform.location.x >= SCRIPTED_ACTOR_DECEL_START_X:
        if not getattr(actor_manager,
                       '_scripted_actor_decel_reported',
                       False):
            print('[SCRIPTED-ACTOR-DECEL] subject longitudinal decel %.1f m/s^2' %
                  -SCRIPTED_ACTOR_DECEL_MPS2)
            actor_manager._scripted_actor_decel_reported = True
        if current_speed_kmh > SCRIPTED_ACTOR_MIN_SPEED_KMH:
            current_speed_kmh = max(
                SCRIPTED_ACTOR_MIN_SPEED_KMH,
                current_speed_kmh - SCRIPTED_ACTOR_DECEL_MPS2 * dt * 3.6)

    if human_brake_active:
        if not getattr(actor_manager,
                       '_human_emergency_decel_reported',
                       False):
            print('[HUMAN-REACTION] subject panic emergency decel %.1f m/s^2 after visual detection' %
                  -HUMAN_EMERGENCY_DECEL_MPS2)
            actor_manager._human_emergency_decel_reported = True
        current_speed_kmh = max(
            HUMAN_EMERGENCY_STOP_SPEED_KMH,
            current_speed_kmh - HUMAN_EMERGENCY_DECEL_MPS2 * dt * 3.6)
    elif (getattr(actor_manager, '_human_visual_reaction_active', False) and
          not getattr(actor_manager,
                      '_human_emergency_decel_release_reported',
                      False)):
        print('[HUMAN-REACTION] subject released brief emergency decel on tick %d' %
              tick_count)
        actor_manager._human_emergency_decel_release_reported = True

    actor_manager._scripted_actor_speed_kmh = current_speed_kmh
    speed_ms = current_speed_kmh / 3.6

    forward_vector = actor_manager._scripted_actor_forward
    right_vector = carla.Vector3D(
        x=forward_vector.y,
        y=-forward_vector.x,
        z=0.0)
    path_origin = actor_manager._scripted_actor_path_origin
    offset_x = transform.location.x - path_origin.x
    offset_y = transform.location.y - path_origin.y
    lateral_error = offset_x * right_vector.x + offset_y * right_vector.y
    lateral_speed = 0.0

    if abs(lateral_error) > SCRIPTED_ACTOR_LANE_TOLERANCE_M:
        lateral_speed = max(
            -SCRIPTED_ACTOR_LATERAL_SPEED_MPS,
            min(SCRIPTED_ACTOR_LATERAL_SPEED_MPS, -1.5 * lateral_error))
        if not getattr(actor_manager,
                       '_scripted_actor_lane_keep_reported',
                       False):
            print('[LANE-KEEP] subject lateral correction up to %.1f m/s toward straight path' %
                  SCRIPTED_ACTOR_LATERAL_SPEED_MPS)
            actor_manager._scripted_actor_lane_keep_reported = True

    vehicle.set_target_velocity(carla.Vector3D(
        x=forward_vector.x * speed_ms + right_vector.x * lateral_speed,
        y=forward_vector.y * speed_ms + right_vector.y * lateral_speed,
        z=0.0))


def _print_v2x_state(key, is_active, message, tick_count, warning_state):
    last_state = warning_state.get(
        key, {'active': False, 'last_print': -999999})

    if is_active:
        should_print = (
            not last_state['active'] or
            tick_count - last_state['last_print'] >=
            V2X_WARNING_PRINT_INTERVAL)
        if should_print:
            print(message)
            warning_state[key] = {
                'active': True,
                'last_print': tick_count
            }
        else:
            warning_state[key] = {
                'active': True,
                'last_print': last_state['last_print']
            }
    else:
        warning_state[key] = {
            'active': False,
            'last_print': last_state['last_print']
        }


def _apply_actor_v2x_yield(control,
                           receiver_manager,
                           actor_manager,
                           receiver_name,
                           actor_name,
                           tick_count,
                           warning_state):
    receiver_actor_distance = receiver_manager.vehicle.get_location().distance(
        actor_manager.vehicle.get_location())
    communication_range = min(_get_v2x_range(receiver_manager),
                              _get_v2x_range(actor_manager))
    is_v2x_active = (
        _is_v2x_enabled(receiver_manager) and
        _is_v2x_enabled(actor_manager) and
        communication_range > 0)
    distance_to_stop = _distance_to_stop_line(receiver_manager,
                                              actor_manager)
    conflict_location = _get_conflict_location(receiver_manager,
                                               actor_manager)
    actor_conflict_distance = actor_manager.vehicle.get_location().distance(
        conflict_location)
    is_in_range = (
        is_v2x_active and
        (receiver_actor_distance <= communication_range or
         actor_conflict_distance <= communication_range))
    key = '%s_to_%s' % (actor_name, receiver_name)
    stop_line_active = getattr(receiver_manager,
                               '_v2x_stop_line_active',
                               False)
    if getattr(receiver_manager, '_v2x_stop_line_released', False):
        return control

    if is_in_range:
        if not stop_line_active:
            receiver_manager._v2x_stop_line_active = True
            stop_line_location, _ = _get_stop_line_state(
                receiver_manager,
                actor_manager)
            print('[V2X-STOP-LINE] %s -> %s: actor info received, link %.2fm, actor-conflict %.2fm <= %.2fm, stop distance %.2fm, stop line=(%.2f, %.2f)' %
                  (actor_name,
                   receiver_name,
                   receiver_actor_distance,
                   actor_conflict_distance,
                   communication_range,
                   distance_to_stop,
                   stop_line_location.x,
                   stop_line_location.y))
        stop_line_active = True

    if stop_line_active:
        if getattr(receiver_manager, '_v2x_stop_line_waiting', False):
            restart_safe, actor_clearance, ttc = _is_v2x_restart_safe(
                receiver_manager,
                actor_manager)
            if restart_safe:
                print('[V2X-RESTART] %s cleared conflict by %.2fm, TTC %s; %s restarting from stop line' %
                      (actor_name,
                       actor_clearance,
                       'safe' if ttc is None else '%.2fs' % ttc,
                       receiver_name))
                return _restart_from_stop_line(control, receiver_manager)

        control, target_speed_kmh, waiting = _apply_stop_line_control(
            control,
            receiver_manager,
            distance_to_stop)
        status_text = 'waiting' if waiting else 'decelerating'
        _print_v2x_state(
            key,
            True,
            '[V2X-STOP-LINE] %s -> %s: %s, link %.2fm, stop distance %.2fm, target %.1f km/h' %
            (actor_name,
             receiver_name,
             status_text,
             receiver_actor_distance,
             distance_to_stop,
             target_speed_kmh),
            tick_count,
            warning_state)
        return control

    last_state = warning_state.get(
        key, {'active': False, 'last_print': -999999})
    if last_state['active']:
        print('[V2X-CLEAR] %s -> %s: link %.2fm > %.2fm' %
              (actor_name,
               receiver_name,
               receiver_actor_distance,
               communication_range))
    _print_v2x_state(key, False, '', tick_count, warning_state)
    return control


def _apply_no_v2x_stop_line_approach(control,
                                     receiver_manager,
                                     actor_manager,
                                     receiver_name,
                                     actor_name,
                                     tick_count,
                                     warning_state):
    if (_is_v2x_enabled(receiver_manager) and
            _is_v2x_enabled(actor_manager)):
        return control

    if getattr(receiver_manager, '_human_visual_reaction_active', False):
        return control

    distance_to_stop = _distance_to_stop_line(receiver_manager,
                                              actor_manager)
    if (distance_to_stop <= 0.0 or
            distance_to_stop > NO_V2X_STOP_LINE_APPROACH_DISTANCE_M):
        _print_v2x_state('no_v2x_stop_line_%s' % receiver_name,
                         False,
                         '',
                         tick_count,
                         warning_state)
        return control

    speed_mps = _get_vehicle_speed_mps(receiver_manager.vehicle)
    target_speed_mps = _get_stop_line_approach_target_mps(
        distance_to_stop,
        NO_V2X_STOP_LINE_APPROACH_DISTANCE_M)
    if target_speed_mps is None:
        target_speed_mps = V2X_STOP_LINE_APPROACH_SPEED_KMH / 3.6

    speed_error_mps = speed_mps - target_speed_mps
    control.throttle = 0.0

    if speed_error_mps > 0.15:
        brake = V2X_STOP_LINE_MIN_BRAKE + speed_error_mps * 0.10
        if distance_to_stop <= V2X_STOP_LINE_CREEP_DISTANCE_M:
            brake = max(brake, 0.28)
        control.brake = max(
            control.brake,
            min(V2X_STOP_LINE_MAX_BRAKE, brake))
    elif speed_mps < target_speed_mps - 0.25:
        control.brake = 0.0
        control.hand_brake = False
        control.throttle = max(
            control.throttle,
            _get_stop_line_roll_throttle(distance_to_stop))

    _print_v2x_state(
        'no_v2x_stop_line_%s' % receiver_name,
        True,
        '[NO-V2X-STOP-LINE] %s approaching unsignalized stop line before seeing %s: stop distance %.2fm, target %.1f km/h' %
        (receiver_name,
         actor_name,
         distance_to_stop,
         target_speed_mps * 3.6),
        tick_count,
        warning_state)
    return control


def run_scenario(opt, scenario_params):
    scenario_manager = None
    eval_manager = None
    single_cav_list = []
    rsu_list = []
    bg_veh_list = []
    recorder_started = False
    topview_recorder = None

    try:
        scenario_params = add_current_time(scenario_params)

        # create CAV world
        cav_world = CavWorld(opt.apply_ml)

        # create scenario manager
        scenario_manager = sim_api.ScenarioManager(scenario_params,
                                                   opt.apply_ml,
                                                   opt.version,
                                                   town='Town04',
                                                   cav_world=cav_world)

        data_dump_enabled = scenario_params.get(
            'vehicle_base', {}).get('datadump', {}).get('enabled', True)

        single_cav_list = \
            scenario_manager.create_vehicle_manager(application=['single'],
                                                    data_dump=data_dump_enabled)
        cav_names = _get_cav_names(scenario_params, len(single_cav_list))
        occluder_index = _get_cav_index(cav_names, ['neighboring', 'bus'], 1)
        actor_index = _get_cav_index(cav_names, ['subject', 'actor'], 2)
        ego_index = _get_cav_index(cav_names, ['ego'], 0)
        max_ticks = scenario_params.get('scenario', {}).get(
            'max_ticks',
            DEFAULT_SCENARIO_MAX_TICKS)
        actor_start_delay_ticks = scenario_params.get('scenario', {}).get(
            'actor_start_delay_ticks',
            0)
        ego_start_delay_ticks = scenario_params.get('scenario', {}).get(
            'ego_start_delay_ticks',
            0)
        v2x_warning_state = {}
        v2x_tick = 0
        occluder_hold_reported = False
        scripted_actor_reported = False
        scripted_actor_delay_reported = False
        scripted_actor_delay_released = False
        ego_start_delay_reported = False
        collision_stop_active = False
        collision_stop_reported = False
        occluder_manager = None

        rsu_list = \
            scenario_manager.create_rsu_manager(data_dump=False)

        # create background traffic in carla
        traffic_manager, bg_veh_list = \
            scenario_manager.create_traffic_carla()
        
        # pedestrian_list = scenario_manager.create_pedestrian_manager(pedestrian_count=100, pedestrian_speed=2)
        
        # while True:
        #     scenario_manager.tick()
        

        # create evaluation manager
        eval_manager = \
            EvaluationManager(scenario_manager.cav_world,
                              script_name='coop_town04',
                              current_time=scenario_params['current_time'])

        spectator = scenario_manager.world.get_spectator()
        topview_recorder = TopViewRecorder(scenario_manager.world,
                                           scenario_params)
        spectator_height = float(scenario_params.get('vehicle_base', {}).get(
            'topview_recording',
            {}).get('height', 70.0))

        # save the data collection protocol to the folder
        current_path = os.path.dirname(os.path.realpath(__file__))
        save_yaml_name = os.path.join(current_path,
                                      '../../data_dumping',
                                      scenario_params['vehicle_base']['datadump']['title'],
                                      scenario_params['current_time'], 
                                      'data_protocol.yaml')
        os.makedirs(os.path.dirname(save_yaml_name), exist_ok=True)
        save_yaml(scenario_params, save_yaml_name)
        # record_name = os.path.join(current_path,
        #                             scenario_params['current_time'],
        #                             "scenario.log")
        if getattr(opt, 'record', False):
            scenario_manager.client.start_recorder(f"../../../../OpenCDA/data_dumping/{scenario_params['vehicle_base']['datadump']['title']}/{scenario_params['current_time']}/scenario.log", True)
            recorder_started = True

        while True:
            v2x_tick += 1
            scenario_manager.tick()
            transform = single_cav_list[0].vehicle.get_transform()
            spectator_transform = carla.Transform(
                transform.location +
                carla.Location(
                    z=spectator_height),
                carla.Rotation(
                    pitch=-
                    90))
            spectator.set_transform(spectator_transform)
            if topview_recorder is not None:
                topview_recorder.set_transform(spectator_transform)

            for i, single_cav in enumerate(single_cav_list):
                single_cav.update_info()
                if _has_collision(single_cav):
                    collision_stop_active = True
                    if not collision_stop_reported:
                        print('[COLLISION-STOP] collision detected; ego and subject held stopped')
                        collision_stop_reported = True

                if occluder_index is not None and i == occluder_index:
                    single_cav.vehicle.apply_control(
                        carla.VehicleControl(throttle=0.0,
                                             brake=OCCLUDER_HOLD_BRAKE,
                                             hand_brake=True))
                    if data_dump_enabled:
                        _dump_vehicle_data(single_cav)
                    if not occluder_hold_reported:
                        print('[OCCLUSION-HOLD] %s bus is held as occluder' %
                              cav_names[i])
                        occluder_hold_reported = True
                    continue

                if collision_stop_active and (
                        i == ego_index or i == actor_index):
                    _hold_after_collision(single_cav)
                    if data_dump_enabled:
                        _dump_vehicle_data(single_cav)
                    continue

                if ego_start_delay_ticks and i == ego_index and \
                        v2x_tick <= ego_start_delay_ticks:
                    single_cav.vehicle.set_target_velocity(
                        carla.Vector3D(0.0, 0.0, 0.0))
                    single_cav.vehicle.apply_control(
                        carla.VehicleControl(throttle=0.0,
                                             brake=1.0,
                                             hand_brake=False))
                    if data_dump_enabled:
                        _dump_vehicle_data(single_cav)
                    if not ego_start_delay_reported:
                        print('[EGO-START-DELAY] %s start delayed by %d ticks for conflict timing' %
                              (cav_names[i], ego_start_delay_ticks))
                        ego_start_delay_reported = True
                    continue

                if actor_index is not None and i == actor_index:
                    if actor_start_delay_ticks and \
                            v2x_tick <= actor_start_delay_ticks:
                        single_cav.vehicle.set_target_velocity(
                            carla.Vector3D(0.0, 0.0, 0.0))
                        single_cav.vehicle.apply_control(
                            carla.VehicleControl(throttle=0.0,
                                                 brake=1.0,
                                                 hand_brake=False))
                        if data_dump_enabled:
                            _dump_vehicle_data(single_cav)
                        if not scripted_actor_delay_reported:
                            print('[SCRIPTED-ACTOR-DELAY] %s start delayed by %d ticks for conflict timing' %
                                  (cav_names[i], actor_start_delay_ticks))
                            scripted_actor_delay_reported = True
                        continue

                    if actor_start_delay_ticks and \
                            not scripted_actor_delay_released:
                        single_cav.vehicle.apply_control(
                            carla.VehicleControl(throttle=0.0,
                                                 brake=0.0,
                                                 hand_brake=False))
                        scripted_actor_delay_released = True

                    _apply_scripted_actor_motion(single_cav,
                                                 tick_count=v2x_tick)
                    if data_dump_enabled:
                        _dump_vehicle_data(single_cav)
                    if not scripted_actor_reported:
                        print('[SCRIPTED-ACTOR] %s drives as level-0 actor at %.1f km/h' %
                              (cav_names[i], SCRIPTED_ACTOR_SPEED_KMH))
                        scripted_actor_reported = True
                    continue

                control = single_cav.run_step()
                if (ego_index is not None and
                        actor_index is not None and
                        i == ego_index):
                    control = _apply_ego_speed_cap(control, single_cav)
                    if occluder_index is not None:
                        occluder_manager = single_cav_list[occluder_index]

                    human_reaction_active = \
                        _apply_human_visual_reaction_if_needed(
                            single_cav,
                            single_cav_list[actor_index],
                            occluder_manager,
                            cav_names[i],
                            cav_names[actor_index],
                            v2x_tick)
                    if human_reaction_active:
                        control = _apply_human_emergency_control(control)
                    else:
                        control = _apply_actor_v2x_yield(
                            control,
                            single_cav,
                            single_cav_list[actor_index],
                            cav_names[i],
                            cav_names[actor_index],
                            v2x_tick,
                            v2x_warning_state)
                        control = _apply_no_v2x_stop_line_approach(
                            control,
                            single_cav,
                            single_cav_list[actor_index],
                            cav_names[i],
                            cav_names[actor_index],
                            v2x_tick,
                            v2x_warning_state)
                        control = _ignore_unseen_no_v2x_hazard_brake(
                            control,
                            single_cav,
                            single_cav_list[actor_index])
                    control = _apply_ego_acceleration_smoothing(
                        control,
                        single_cav)
                single_cav.vehicle.apply_control(control)

            for rsu in rsu_list:
                rsu.update_info()
                rsu.run_step()

            if max_ticks and v2x_tick >= max_ticks:
                print('[SCENARIO-END] scenario_1 completed at tick %d' %
                      v2x_tick)
                break

    finally:
        if eval_manager is not None:
            eval_manager.evaluate()

        if topview_recorder is not None:
            topview_recorder.destroy()

        # if opt.record:
        if scenario_manager is not None and recorder_started:
            scenario_manager.client.stop_recorder()

        if scenario_manager is not None:
            scenario_manager.close()

        for v in single_cav_list:
            v.destroy()
        for r in rsu_list:
            r.destroy()
        for v in bg_veh_list:
            v.destroy()
        # for p in pedestrian_list:
        #     p.destroy()
