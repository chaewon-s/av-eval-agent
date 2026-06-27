# -*- coding: utf-8 -*-
"""
Dumping sensor data.
"""

# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: TDG-Attribution-NonCommercial-NoDistrib

import os

import cv2
import open3d as o3d
import numpy as np

from opencda.core.common.misc import get_speed
from opencda.core.sensing.perception import sensor_transformation as st
from opencda.scenario_testing.utils.yaml_utils import save_yaml


class DataDumper(object):
    """
    Data dumper class to save data in local disk.

    Parameters
    ----------
    perception_manager : opencda object
        The perception manager contains rgb camera data and lidar data.

    vehicle_id : int
        The carla.Vehicle id.

    save_time : str
        The timestamp at the beginning of the simulation.

    Attributes
    ----------
    rgb_camera : list
        A list of opencda.CameraSensor that containing all rgb sensor data
        of the managed vehicle.

    lidar ; opencda object
        The lidar manager from perception manager.

    save_parent_folder : str
        The parent folder to save all data related to a specific vehicle.

    count : int
        Used to count how many steps have been executed. We dump data
        every 10 steps.

    """

    def __init__(self,
                 perception_manager,
                 vehicle_id,
                 save_time,
                 scenario_title):

        self.rgb_camera = perception_manager.rgb_camera
        self.lidar = perception_manager.lidar

        self.save_time = save_time
        self.vehicle_id = vehicle_id
        self.scenario_title = scenario_title

        current_path = os.path.dirname(os.path.realpath(__file__))
        self.save_parent_folder = \
            os.path.join(current_path,
                         '../../../data_dumping',
                         self.scenario_title,
                         save_time,
                         str(self.vehicle_id))
        self.relative_save_parent_folder = \
            os.path.join('data_dumping',
                         self.scenario_title,
                         save_time,
                         str(self.vehicle_id))

        if not os.path.exists(self.save_parent_folder):
            os.makedirs(self.save_parent_folder)
        if not os.path.exists(self.relative_save_parent_folder):
            os.makedirs(self.relative_save_parent_folder)

        self.count = 0

    def run_step(self,
                 perception_manager,
                 localization_manager,
                 behavior_agent):
        """
        Dump data at running time.

        Parameters
        ----------
        perception_manager : opencda object
            OpenCDA perception manager.

        localization_manager : opencda object
            OpenCDA localization manager.

        behavior_agent : opencda object
            Open
        """
        self.count += 1
        # we ignore the first 60 steps
        # if self.count < 60:
        #     return

        # 10hz
        # if self.count % 2 != 0:
        #     return

        self.save_rgb_image(self.count)
        self.save_lidar_points()
        self.save_yaml_file(perception_manager,
                            localization_manager,
                            behavior_agent,
                            self.count)

    def save_rgb_image(self, count):
        """
        Save camera rgb images to disk.
        """
        if not self.rgb_camera:
            return

        for (i, camera) in enumerate(self.rgb_camera):

            frame = camera.frame
            image = camera.image
            if image is None:
                continue

            image_name = '%06d' % count + '_' + 'camera%d' % i + '.png'
            # cv2.imwrite(os.path.join(self.save_parent_folder, image_name),
            #             image)
            cv2.imwrite(os.path.join(self.relative_save_parent_folder,
                                     image_name),
                        image)

    def save_lidar_points(self):
        """
        Save 3D lidar points to disk.
        """
        if self.lidar is None or self.lidar.data is None:
            return

        point_cloud = self.lidar.data
        frame = self.lidar.frame

        point_xyz = point_cloud[:, :-1]
        point_intensity = point_cloud[:, -1]
        point_intensity = np.c_[
            point_intensity,
            np.zeros_like(point_intensity),
            np.zeros_like(point_intensity)
        ]

        o3d_pcd = o3d.geometry.PointCloud()
        o3d_pcd.points = o3d.utility.Vector3dVector(point_xyz)
        o3d_pcd.colors = o3d.utility.Vector3dVector(point_intensity)

        # write to pcd file
        pcd_name = '%06d' % frame + '.pcd'
        o3d.io.write_point_cloud(os.path.join(self.relative_save_parent_folder,
                                              pcd_name),
                                 pointcloud=o3d_pcd,
                                 write_ascii=True)

    def save_yaml_file(self,
                       perception_manager,
                       localization_manager,
                       behavior_agent,
                       count):
        """
        Save objects positions/spped, true ego position,
        predicted ego position, sensor transformations.

        Parameters
        ----------
        perception_manager : opencda object
            OpenCDA perception manager.

        localization_manager : opencda object
            OpenCDA localization manager.

        behavior_agent : opencda object
            OpenCDA behavior agent.
        """
        frame = count

        dump_yml = {}
        vehicle_dict = {}

        # dump obstacle vehicles first
        objects = perception_manager.objects
        vehicle_list = objects.get('vehicles', [])
        pcd_list = objects.get('vehicles_pcd', {})

        for index, veh in enumerate(vehicle_list):
            veh_carla_id = getattr(veh, 'carla_id', -1)
            prediction_id = getattr(veh, 'prediction_id', None)
            veh_pos = veh.get_transform()
            veh_location = veh.get_location()
            veh_bbx = veh.bounding_box
            veh_speed = get_speed(veh)
            veh_velocity = veh.get_velocity()

            if veh_pos is not None:
                roll = veh_pos.rotation.roll
                yaw = veh_pos.rotation.yaw
                pitch = veh_pos.rotation.pitch
            else:
                roll = 0.0
                yaw = 0.0
                pitch = 0.0

            if prediction_id is None:
                prediction_id = veh_carla_id if veh_carla_id != -1 else index
            vehicle_key = veh_carla_id if veh_carla_id != -1 \
                else 'pred_%s' % prediction_id

            vehicle_dict.update({vehicle_key: {
                'bp_id': getattr(veh, 'type_id', 'detected_vehicle'),
                'color': getattr(veh, 'color', None),
                'carla_id': int(veh_carla_id),
                'pr_id': int(prediction_id),
                'matched_gt_id': int(getattr(veh, 'matched_gt_id',
                                             veh_carla_id)),
                'match_distance': float(getattr(veh, 'match_distance', 0.0)),
                'perception_mode': objects.get('perception_mode',
                                               'server_or_semantic'),
                "location": [veh_location.x,
                             veh_location.y,
                             veh_location.z],
                "center": [veh_bbx.location.x,
                           veh_bbx.location.y,
                           veh_bbx.location.z],
                "angle": [roll,
                          yaw,
                          pitch],
                "extent": [veh_bbx.extent.x,
                           veh_bbx.extent.y,
                           veh_bbx.extent.z],
                "speed": veh_speed,
                "velocity": [veh_velocity.x, veh_velocity.y, veh_velocity.z],
                "number of pcd": len(pcd_list[veh_carla_id])
                if veh_carla_id in pcd_list.keys() else 0
            }})

        dump_yml.update({'vehicles': vehicle_dict})

        ## TOTAL VEHICLES

        try:
            total_vehicle_list = objects.get('total_vehicles', [])
            pcd_list = objects.get('total_vehicles_pcd', {})
            total_vehicle_dict = {}
            for veh in total_vehicle_list:
                veh_carla_id = getattr(veh, 'carla_id', -1)
                veh_pos = veh.get_transform()
                veh_bbx = veh.bounding_box
                veh_speed = get_speed(veh)
                veh_velocity = veh.get_velocity()

                total_vehicle_dict.update({veh_carla_id: {
                    'bp_id': getattr(veh, 'type_id', 'vehicle'),
                    'color': getattr(veh, 'color', None),
                    'carla_id': int(veh_carla_id),
                    "location": [veh_pos.location.x,
                                veh_pos.location.y,
                                veh_pos.location.z],
                    "center": [veh_bbx.location.x,
                            veh_bbx.location.y,
                            veh_bbx.location.z],
                    "angle": [veh_pos.rotation.roll,
                            veh_pos.rotation.yaw,
                            veh_pos.rotation.pitch],
                    "extent": [veh_bbx.extent.x,
                            veh_bbx.extent.y,
                            veh_bbx.extent.z],
                    "speed": veh_speed,
                    "velocity": [veh_velocity.x, veh_velocity.y, veh_velocity.z],
                    "number of pcd": len(pcd_list[veh_carla_id]) if veh_carla_id in pcd_list.keys() else 0
                }})

            dump_yml.update({'total_vehicles': total_vehicle_dict})
        except:
            print("")

        # dump ego pose and speed, if vehicle does not exist, then it is
        # a rsu(road side unit).
        predicted_ego_pos = localization_manager.get_ego_pos()
        true_ego_pos = localization_manager.vehicle.get_transform() \
            if hasattr(localization_manager, 'vehicle') \
            else localization_manager.true_ego_pos

        dump_yml.update({'predicted_ego_pos': [
            predicted_ego_pos.location.x,
            predicted_ego_pos.location.y,
            predicted_ego_pos.location.z,
            predicted_ego_pos.rotation.roll,
            predicted_ego_pos.rotation.yaw,
            predicted_ego_pos.rotation.pitch]})
        dump_yml.update({'true_ego_pos': [
            true_ego_pos.location.x,
            true_ego_pos.location.y,
            true_ego_pos.location.z,
            true_ego_pos.rotation.roll,
            true_ego_pos.rotation.yaw,
            true_ego_pos.rotation.pitch]})
        dump_yml.update({'ego_speed':
                        float(localization_manager.get_ego_spd())})
        
        ego_vel = localization_manager.get_ego_velocity()
        dump_yml.update({'ego_velocity':
                        [ego_vel.x, ego_vel.y, ego_vel.z]})

        # dump lidar sensor coordinates under world coordinate system
        if self.lidar:
            lidar_transformation = self.lidar.sensor.get_transform()
            dump_yml.update({'lidar_pose': [
                lidar_transformation.location.x,
                lidar_transformation.location.y,
                lidar_transformation.location.z,
                lidar_transformation.rotation.roll,
                lidar_transformation.rotation.yaw,
                lidar_transformation.rotation.pitch]})

        # dump camera sensor coordinates under world coordinate system
        if self.rgb_camera:
            for (i, camera) in enumerate(self.rgb_camera):
                camera_param = {}
                camera_transformation = camera.sensor.get_transform()
                camera_param.update({'cords': [
                    camera_transformation.location.x,
                    camera_transformation.location.y,
                    camera_transformation.location.z,
                    camera_transformation.rotation.roll,
                    camera_transformation.rotation.yaw,
                    camera_transformation.rotation.pitch
                ]})

                # dump intrinsic matrix
                camera_intrinsic = st.get_camera_intrinsic(camera.sensor)
                camera_intrinsic = self.matrix2list(camera_intrinsic)
                camera_param.update({'intrinsic': camera_intrinsic})

                # dump extrinsic matrix lidar2camera
                if self.lidar:
                    lidar2world = st.x_to_world_transformation(
                        self.lidar.sensor.get_transform())
                    camera2world = st.x_to_world_transformation(
                        camera.sensor.get_transform())

                    world2camera = np.linalg.inv(camera2world)
                    lidar2camera = np.dot(world2camera, lidar2world)
                    lidar2camera = self.matrix2list(lidar2camera)
                    camera_param.update({'extrinsic': lidar2camera})

                dump_yml.update({'camera%d' % i: camera_param})

        dump_yml.update({'RSU': True})
        # dump the planned trajectory if it exisit.
        if behavior_agent is not None:
            trajectory_deque = \
                behavior_agent.get_local_planner().get_trajectory()
            trajectory_list = []

            for i in range(len(trajectory_deque)):
                tmp_buffer = trajectory_deque.popleft()
                x = tmp_buffer[0].location.x
                y = tmp_buffer[0].location.y
                spd = tmp_buffer[1]

                trajectory_list.append([x, y, spd])

            dump_yml.update({'plan_trajectory': trajectory_list})
            dump_yml.update({'RSU': False})

        yml_name = '%06d' % frame + '.yaml'
        save_path = os.path.join(self.relative_save_parent_folder,
                                 yml_name)

        save_yaml(dump_yml, save_path)

    @staticmethod
    def matrix2list(matrix):
        """
        To generate readable yaml file, we need to convert the matrix
        to list format.

        Parameters
        ----------
        matrix : np.ndarray
            The extrinsic/intrinsic matrix.

        Returns
        -------
        matrix_list : list
            The matrix represents in list format.
        """

        assert len(matrix.shape) == 2
        return matrix.tolist()
