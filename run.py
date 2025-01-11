import argparse
import re
from functools import partial

from tqdm import tqdm
from dotenv import load_dotenv
import mosspy
import yaml
import os
import glob
from pathlib import Path
import gitlab
import git
from typing import List
import time
from moss_task import MossTask, TaskManager

DEFAULT_MOSS_OPTIONS = {
    'm': 20,
    'd': 0,
    'x': 0,
    'c': '',
    'n': 1000
}

DEFAULT_CONFIG = {
    'lang': 'c',
    'output': 'output/',
    'moss_request_cooldown': 60,
    'base_repos': [],
    'base_files': ['*.*'],
    'gitlab_group': 'cse101',
    'this_quarter_groups': [],
    'previous_quarter_groups': [],
    'assignment_branch': 'main',
    'assignment_path': '',
    'assignment_files': ['*/*.c', '*/*.cpp', '*/*.cc'],
}

load_dotenv()
GITLAB_TOKEN = os.getenv('GITLAB_TOKEN')
GITLAB_URL = os.getenv('GITLAB_URL')

FILES_NUM_LIMIT = 350
MIN_FILES_NUM = 50


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='Moss Terminal',
        description='Measure Of Software Similarity (MOSS) Automation for CSE101')
    parser.add_argument('-c', '--config',
                        type=str,
                        required=True,
                        help='Path to config file.')
    parser.add_argument('-o', '--output',
                        type=str,
                        default=None,
                        help='Output path.')
    parser.add_argument('-g', '--git_clone',
                        action="store_true",
                        default=False,
                        help='If set, do not clone the repositories.')
    parser.add_argument('-m', '--moss',
                        action="store_true",
                        default=False,
                        help='Run Moss.')
    parser.add_argument('-r', '--resume',
                        action="store_true",
                        default=False,
                        help='Resume Moss.')
    return parser


def load_config(arguments) -> dict:
    try:
        with open(arguments.config, 'r') as conf_file:
            conf = yaml.load(conf_file, Loader=yaml.SafeLoader)
    except OSError as os_ex:
        raise Exception(f'Could not open the config file {arguments.config}') from os_ex
    config = DEFAULT_CONFIG.copy()
    config.update(conf)
    if arguments.output is not None:
        config['output'] = arguments.output

    moss_options = DEFAULT_MOSS_OPTIONS.copy()
    if 'moss_options' in config:
        moss_options.update(config['moss_options'])
    config['moss_options'] = moss_options
    return config


def create_moss_tasks(config: dict) -> List[MossTask]:
    lang = config['lang']
    base_path = config['base_path']
    assignment_path = config['assignment_path']
    assignment_files = config['assignment_files']
    this_quarter_groups = config['this_quarter_groups']
    previous_quarter_groups = config['previous_quarter_groups']

    base_files = []
    for base_file in config['base_files']:
        base_files += load_files(base_path, base_file, lang=lang, recursive=True)

    tasks = []
    for assignment_file in assignment_files:
        for this_group in this_quarter_groups:
            this_quarter_files = load_files(os.path.join(config['files_path'], this_group),
                                            os.path.join(assignment_path, assignment_file), lang=lang)
            remaining_size = FILES_NUM_LIMIT - len(this_quarter_files)
            for prev_group in previous_quarter_groups:
                print(prev_group)
                prev_quarter_files = load_files(os.path.join(config['files_path'], prev_group),
                                                os.path.join(assignment_path, assignment_file), lang=lang)
                size = max(min(MIN_FILES_NUM, len(prev_quarter_files)), min(remaining_size, len(prev_quarter_files)))
                for i, s in enumerate(range(0, len(prev_quarter_files), size)):
                    name = f'{this_group}_{prev_group}_{assignment_file}_p{i + 1}'
                    report_path = os.path.join(config['output'], 'moss_results', f'{this_group}_{prev_group}', assignment_file,
                                               f'part_{i + 1}')
                    task = MossTask(report_path, name, files=this_quarter_files + prev_quarter_files[s:s + size],
                                    base_files=base_files, lang=lang, file_path=config['files_path'])
                    tasks.append(task)
            name = f'{this_group}_{this_group}_{assignment_file}_p1'
            report_path = os.path.join(config['output'], 'moss_results', f'{this_group}_{this_group}', assignment_file, f'part_1')
            task = MossTask(report_path, name, files=this_quarter_files, base_files=base_files, lang=lang, file_path=config['files_path'])
            tasks.append(task)
    return tasks


def load_files(path, file_wildcard, lang='c', recursive=False) -> List[str]:
    files = get_files(path, file_wildcard, recursive=recursive)
    partial_filter = partial(check_file_validity, lang=lang)
    return list(filter(partial_filter, files))


def get_files(path, file_wildcard, recursive=False):
    pattern = os.path.join(path, '**', file_wildcard)
    return glob.glob(pattern, recursive=recursive)


def remove_c_comments(text):
    pattern = r"/\*[^*]*\*+([^/*][^*]*\*+)*/|(\"(\\.|[^\"\\\n])*\"|'(\\.|[^\'\\\n])*'|[^/\"'\\]*)"
    return ''.join(m.group(2) for m in re.finditer(pattern, text, re.M | re.S) if m.group(2))


def is_empty(text):
    for ch in text:
        if ch.isalnum():
            return False
    return True


def check_file_validity(path, lang='c'):
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) == 0:
        return False
    # if lang == 'c' or lang == 'cc':
    #     try:
    #         with open(path, 'r') as f:
    #             string = ''
    #             for line in f.readlines():
    #                 if not line.strip().startswith('//'):
    #                     string += line + '\n'
    #             return not is_empty(remove_c_comments(string))
    #     except Exception as ex:
    #         print(ex)
    return True


def clone_repos(config: dict):
    base_repos = config['base_repos']
    this_quarter_groups = config['this_quarter_groups']
    previous_quarter_groups = config['previous_quarter_groups']
    if not os.path.exists(config['files_path']):
        os.makedirs(config['files_path'])

    gl = gitlab.Gitlab(url=GITLAB_URL, private_token=GITLAB_TOKEN)
    gl.auth()
    for repo in base_repos:
        clone_repo(repo, config['base_path'], '')
    for group in gitlab_get_groups(gl, this_quarter_groups):
        gitlab_clone_group(group, config['files_path'], branch=config['assignment_branch'])
    for group in gitlab_get_groups(gl, previous_quarter_groups):
        gitlab_clone_group(group, config['files_path'], branch=config['assignment_branch'])


def gitlab_get_groups(gl: gitlab.Gitlab, group_names: List[str]):
    group_list = []
    for group in gl.groups.list(get_all=True):
        if group.name in group_names:
            group_list.append(group)
    return group_list


def clone_repo(ssh_url_to_repo, path, name, branch='main'):
    repo_path = os.path.join(path, name)
    if not os.path.exists(repo_path):
        try:
            git.Repo.clone_from(ssh_url_to_repo, repo_path, branch=branch)
        except git.exc.GitCommandError:
            try:
                git.Repo.clone_from(ssh_url_to_repo, repo_path)
            except Exception as e:
                print(e)


def gitlab_clone_group(group, path: str, branch=None):
    group_path = os.path.join(path, group.name)
    os.makedirs(group_path, exist_ok=True)
    projects = group.projects.list(get_all=True)
    print(f'Cloning {group.name}:')
    for project in tqdm(projects):
        clone_repo(project.ssh_url_to_repo, group_path, project.name, branch)


def main(arguments):
    config = load_config(arguments)
    if arguments.output is not None:
        config['output'] = args.output
    output_path = config['output']
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    if config['this_quarter_groups'] is None or len(config['this_quarter_groups']) == 0:
        raise Exception('This quarter groups cannot be empty.')

    # if config['previous_quarter_groups'] is None or len(config['previous_quarter_groups']) == 0:
    #     raise Exception('Previous quarter groups cannot be empty.')

    config['files_path'] = os.path.join(config['output'], 'files')
    config['base_path'] = os.path.join(config['files_path'], 'base')

    if arguments.git_clone:
        clone_repos(config)
    else:
        task_manager = TaskManager(output_path, task_cooldown=config['moss_request_cooldown'],
                                   resume=arguments.resume)
        if not arguments.resume:
            tasks = create_moss_tasks(config)
            for task in tasks:
                task_manager.add_task(task)
        task_manager.run()


if __name__ == '__main__':
    arg_parser = build_arg_parser()
    args = arg_parser.parse_args()
    if not args.moss and not args.git_clone:
        args.eror("Either --moss or --git_clone can be present.")
    if not args.moss and args.resume:
        args.eror("--resume can only be present when --moss is present.")
    main(args)
