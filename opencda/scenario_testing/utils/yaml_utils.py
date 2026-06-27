# -*- coding: utf-8 -*-
"""
Used to load and write yaml files
"""
# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: TDG-Attribution-NonCommercial-NoDistrib

import os
from datetime import datetime

import yaml
from omegaconf import OmegaConf


def _load_config_with_default(file):
    """
    Load a yaml file and merge it with default.yaml when it is one of the
    scenario config files.
    """
    config = OmegaConf.load(file)

    config_dir = os.path.dirname(os.path.abspath(file))
    default_path = os.path.join(config_dir, 'default.yaml')
    is_scenario_config = os.path.basename(config_dir) == 'config_yaml'
    is_default_file = os.path.basename(file) == 'default.yaml'

    if is_scenario_config and not is_default_file and os.path.exists(default_path):
        default_config = OmegaConf.load(default_path)
        config = OmegaConf.merge(default_config, config)

    return config

def load_yaml(file):
    """
    Load yaml file and return a dictionary.
    Parameters
    ----------
    file : string
        yaml file path.

    Returns
    -------
    param : dict
        A dictionary that contains defined parameters.
    """

    param = _load_config_with_default(file)

    # load current time for data dumping and evaluation
    current_time = datetime.now()
    current_time = current_time.strftime("%Y_%m_%d_%H_%M_%S")

    param['current_time'] = current_time

    return param


def add_current_time(params):
    """
    Add current time to the params dictionary.
    """
    # load current time for data dumping and evaluation
    current_time = datetime.now()
    current_time = current_time.strftime("%Y_%m_%d_%H_%M_%S")

    params['current_time'] = current_time

    return params


def save_yaml(data, save_name):
    """
    Save the dictionary into a yaml file.

    Parameters
    ----------
    data : dict
        The dictionary contains all data.

    save_name : string
        Full path of the output yaml file.
    """
    if isinstance(data, dict):
        with open(save_name, 'w', encoding='utf-8') as outfile:
            yaml.safe_dump(data, outfile,
                           default_flow_style=False,
                           allow_unicode=True)
    else:
        with open(save_name, "w", encoding='utf-8') as f:
            OmegaConf.save(data, f)

