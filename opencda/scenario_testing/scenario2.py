# -*- coding: utf-8 -*-
"""
Scenario testing: Single vehicle dring in the customized 2 lane highway map.
"""
# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: TDG-Attribution-NonCommercial-NoDistrib

import argparse
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
SCENARIO_RUNNER = os.path.join(REPO_ROOT, 'scenario_runner')
if os.path.isdir(SCENARIO_RUNNER) and SCENARIO_RUNNER not in sys.path:
    sys.path.insert(0, SCENARIO_RUNNER)

import carla

import opencda.scenario_testing.utils.sim_api as sim_api
import opencda.scenario_testing.utils.customized_map_api as map_api

from opencda.core.common.cav_world import CavWorld
from opencda.scenario_testing.evaluations.evaluate_manager import \
    EvaluationManager
from opencda.scenario_testing.utils.yaml_utils import \
    add_current_time, save_yaml
from omegaconf import OmegaConf


DEFAULT_AGENT_MAX_TICKS = 220


def _dump_dir(current_path, scenario_params):
    return os.path.abspath(os.path.join(
        current_path,
        '../../data_dumping',
        scenario_params['vehicle_base']['datadump']['title'],
        scenario_params['current_time']))


def _save_data_protocol(current_path, scenario_params):
    dump_dir = _dump_dir(current_path, scenario_params)
    os.makedirs(dump_dir, exist_ok=True)
    save_yaml(scenario_params, os.path.join(dump_dir, 'data_protocol.yaml'))
    return dump_dir


def run_scenario(opt, scenario_params):
    scenario_manager = None
    eval_manager = None
    single_cav_list = []
    bg_veh_list = []
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

        dump_dir = _save_data_protocol(current_path, scenario_params)
        scenario_manager.client.start_recorder(
            os.path.join(dump_dir, 'scenario.log'), True)
        recorder_started = True
        tick_count = 0
        ticks_limit = getattr(opt, 'ticks', None)
        if ticks_limit is None:
            ticks_limit = scenario_params.get('scenario', {}).get(
                'max_ticks', DEFAULT_AGENT_MAX_TICKS)
        # run steps
        while True:
            scenario_manager.tick()
            tick_count += 1
            transform = single_cav_list[0].vehicle.get_transform()
            spectator.set_transform(carla.Transform(
                transform.location +
                carla.Location(
                    z=70),
                carla.Rotation(
                    pitch=-
                    90,
                    yaw=-
                    90)))

            for i, single_cav in enumerate(single_cav_list):
                single_cav.update_info()
                control = single_cav.run_step()
                single_cav.vehicle.apply_control(control)
            if ticks_limit is not None and tick_count >= ticks_limit:
                break

    finally:
        if eval_manager is not None:
            eval_manager.evaluate()

        if recorder_started and scenario_manager is not None:
            scenario_manager.client.stop_recorder()

        if scenario_manager is not None:
            scenario_manager.close()

        for v in single_cav_list:
            v.destroy()
        for v in bg_veh_list:
            v.destroy()


def _load_scenario_params(config_name):
    current_path = os.path.dirname(os.path.realpath(__file__))
    config_dir = os.path.join(current_path, 'config_yaml')
    return OmegaConf.merge(
        OmegaConf.load(os.path.join(config_dir, 'default.yaml')),
        OmegaConf.load(os.path.join(config_dir, f'{config_name}.yaml')))


def main():
    parser = argparse.ArgumentParser(
        description='Run Scenario 2 without V2X and save Scenario 1-style logs.')
    parser.add_argument('--config', default='scenario2',
                        help='Config YAML name without .yaml.')
    parser.add_argument('--version', default='0.9.14',
                        help='CARLA/OpenCDA version string.')
    parser.add_argument('--apply-ml', action='store_true',
                        help='Enable ML perception if configured.')
    parser.add_argument('--ticks', type=int, default=None,
                        help='Stop after N ticks. Omit to run until interrupted.')
    opt = parser.parse_args()
    run_scenario(opt, _load_scenario_params(opt.config))


if __name__ == '__main__':
    main()
