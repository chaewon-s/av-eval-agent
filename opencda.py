import argparse
import importlib
import os
import sys

from opencda.scenario_testing.utils.yaml_utils import load_yaml


def _build_parser():
    parser = argparse.ArgumentParser(
        description='Run an OpenCDA scenario testing script.')
    parser.add_argument(
        '-t', '--test_scenario',
        required=True,
        dest='scenario_name',
        help='Scenario name under opencda/scenario_testing/')
    parser.add_argument(
        '-v', '--version',
        default='0.9.14',
        help='CARLA simulator version')
    parser.add_argument(
        '--apply_ml',
        action='store_true',
        help='Load ML-based perception models')
    parser.add_argument(
        '--record',
        action='store_true',
        help='Enable CARLA recorder when supported by the scenario')
    return parser


def _load_scenario_module(scenario_name):
    try:
        return importlib.import_module(
            'opencda.scenario_testing.%s' % scenario_name)
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Scenario module '%s' was not found." % scenario_name) from exc


def _load_scenario_config(scenario_name):
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'opencda',
        'scenario_testing',
        'config_yaml',
        '%s.yaml' % scenario_name)

    if not os.path.exists(config_path):
        raise SystemExit(
            "Scenario config '%s' was not found." % config_path)

    return load_yaml(config_path)


def main():
    parser = _build_parser()
    opt = parser.parse_args()

    scenario_module = _load_scenario_module(opt.scenario_name)
    if not hasattr(scenario_module, 'run_scenario'):
        raise SystemExit(
            "Scenario module '%s' does not expose run_scenario()." %
            opt.scenario_name)

    scenario_params = _load_scenario_config(opt.scenario_name)
    scenario_module.run_scenario(opt, scenario_params)


if __name__ == '__main__':
    main()
