# -*- coding: utf-8 -*-
"""
Scenario testing: merging vehicle joining a platoon in the
customized 2-lane freeway simplified map sorely with carla
"""
# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: TDG-Attribution-NonCommercial-NoDistrib
import os

import carla

import opencda.scenario_testing.utils.sim_api as sim_api
from opencda.core.common.cav_world import CavWorld
from opencda.scenario_testing.evaluations.evaluate_manager import \
    EvaluationManager
from opencda.scenario_testing.utils.yaml_utils import add_current_time, save_yaml


def _is_stationary_vehicle(cav_config):
    """Keep the scenario bus fixed in place without changing planner settings."""
    vehicle_type = str(cav_config.get('vehicle_type', '')).lower()
    name = str(cav_config.get('name', '')).lower()
    return name == 'neighboring' or 'fusorosa' in vehicle_type


def run_scenario(opt, scenario_params):
    eval_manager = None
    scenario_manager = None
    single_cav_list = []
    rsu_list = []
    bg_veh_list = []
    recorder_started = False
    data_dump_enabled = False
    record_enabled = False
    stationary_vehicle_indices = set()
    stationary_control = carla.VehicleControl(
        throttle=0.0,
        brake=1.0,
        hand_brake=True)

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



        single_cav_list = \
            scenario_manager.create_vehicle_manager(application=['single'],
                                                    data_dump=data_dump_enabled)
        rsu_list = \
            scenario_manager.create_rsu_manager(data_dump=data_dump_enabled)

        stationary_vehicle_indices = {
            i for i, cav_config in enumerate(
                scenario_params['scenario']['single_cav_list'])
            if _is_stationary_vehicle(cav_config)
        }
        for index in stationary_vehicle_indices:
            vehicle = single_cav_list[index].vehicle
            vehicle.set_target_velocity(carla.Vector3D())
            vehicle.set_target_angular_velocity(carla.Vector3D())
            vehicle.apply_control(stationary_control)

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

        # save the data collection protocol to the folder
        current_path = os.path.dirname(os.path.realpath(__file__))

        # if os.path.exists(os.path.join(current_path, 
        #                                '../../data_dumping', scenario_params['datadump']['title'])):
        #     os.makedirs(os.path.join(current_path, 
        #                                '../../data_dumping', scenario_params['datadump']['title']))
            
        if data_dump_enabled:
            save_yaml_name = os.path.join(
                current_path,
                '../../data_dumping',
                scenario_params['vehicle_base']['datadump']['title'],
                scenario_params['current_time'],
                'data_protocol.yaml')
            save_yaml(scenario_params, save_yaml_name)

        if record_enabled:
            scenario_manager.client.start_recorder(
                f"../../../../OpenCDA/data_dumping/{scenario_params['vehicle_base']['datadump']['title']}/{scenario_params['current_time']}/scenario.log",
                True)
            recorder_started = True

        while True:
            scenario_manager.tick()
            transform = single_cav_list[0].vehicle.get_transform()
            spectator.set_transform(carla.Transform(
                transform.location +
                carla.Location(
                    z=70),
                carla.Rotation(
                    pitch=-
                    90)))

            for i, single_cav in enumerate(single_cav_list):
                if i in stationary_vehicle_indices:
                    single_cav.vehicle.set_target_velocity(carla.Vector3D())
                    single_cav.vehicle.set_target_angular_velocity(
                        carla.Vector3D())
                    single_cav.vehicle.apply_control(stationary_control)
                    continue
                single_cav.update_info()
                control = single_cav.run_step()
                single_cav.vehicle.apply_control(control)

            for rsu in rsu_list:
                rsu.update_info()
                rsu.run_step()

    finally:
        if eval_manager is not None:
            eval_manager.evaluate()

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
