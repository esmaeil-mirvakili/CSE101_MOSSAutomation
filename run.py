import argparse
import math
import re
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

DEFAULT_CONFIG = {
    'lang': 'c',
    'output': 'output/',
    'files': 'files/',
    'moss_request_cooldown': 60,
    'base_repos': [],
    'base_files': ['*.*'],
    'gitlab_group': 'cse101',
    'this_quarter_project': [],
    'previous_quarter_project': [],
    'assignment_branch': 'main',
    'assignment_path': '',
    'assignment_files': ['*/*.c', '*/*.cpp', '*/*.cc'],
}

DEFAULT_MOSS_OPTIONS = {
    'm': 20,
    'd': 0,
    'x': 0,
    'c': '',
    'n': 1000
}

load_dotenv()
gitlab_token = os.getenv('GITLAB_TOKEN')
gitlab_url = os.getenv('GITLAB_URL')
moss_userid = os.getenv('USER_ID')

file_num_limit = 300


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
    parser.add_argument('-ng', '--no_git_clone',
                        action="store_true",
                        default=False,
                        help='If set, do not clone the repositories.')
    return parser


def load_config(path: str) -> dict:
    try:
        with open(path, 'r') as conf_file:
            conf = yaml.load(conf_file, Loader=yaml.SafeLoader)
    except OSError as os_ex:
        raise Exception(f'Could not open the config file {path}') from os_ex
    return conf


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
            except:
                pass


def gitlab_clone_group(group, group_path: str, branch=None):
    projects = group.projects.list(get_all=True)
    print(f'Cloning {group.name}:')
    for project in tqdm(projects):
        clone_repo(project.ssh_url_to_repo, group_path, project.name, branch)


def setup_files(group_list: List[str], path: str, branch=None):
    gl = gitlab.Gitlab(url=gitlab_url, private_token=gitlab_token)
    gl.auth()
    for group in gitlab_get_groups(gl, group_list):
        group_path = os.path.join(path, group.name)
        os.makedirs(group_path, exist_ok=True)
        gitlab_clone_group(group, group_path, branch)


def get_files(path, file_wildcard, assignment_path=None):
    if assignment_path is not None:
        pattern = os.path.join(path, '**', assignment_path, file_wildcard)
    else:
        pattern = os.path.join(path, '**', file_wildcard)
    return glob.glob(pattern, recursive=False)


def remove_c_comments(text):
    pattern = r"/\*[^*]*\*+([^/*][^*]*\*+)*/|(\"(\\.|[^\"\\\n])*\"|'(\\.|[^\'\\\n])*'|[^/\"'\\]*)"
    return ''.join(m.group(2) for m in re.finditer(pattern, text, re.M|re.S) if m.group(2))


def is_empty(text):
    for ch in text:
        if ch.isalnum():
            return False
    return True


def check_file_validity(path, lang):
    if lang == 'c' or lang == 'cc':
        try:
            with open(path, 'r') as f:
                string = ''
                for line in f.readlines():
                    if not line.strip().startswith('//'):
                        string += line + '\n'
                return not is_empty(remove_c_comments(string))
        except:
            pass
    return True


def run_moss(output_path, lang, moss_options, base_files, assignment_files, prev_assignment_group,
             prev_assignment_files, name, exclude=''):

    # return
    m = mosspy.Moss(moss_userid, lang)

    m.options.update(moss_options)

    for base_file in base_files:
        if os.path.getsize(base_file) > 0:
            m.addBaseFile(base_file)
    ass_cnt = 0
    pre_cnt = 0
    for i, assignment_file in enumerate(assignment_files):
        if os.path.getsize(assignment_file) > 0 and check_file_validity(assignment_file, lang):
            ass_cnt += 1
            m.addFile(assignment_file, display_name=assignment_file.replace(exclude, ''))
    for i, prev_assignment_file in enumerate(prev_assignment_files):
        if os.path.getsize(prev_assignment_file) > 0 and check_file_validity(prev_assignment_file, lang):
            pre_cnt += 1
            m.addFile(prev_assignment_file, display_name=prev_assignment_file.replace(exclude, ''))
    print(ass_cnt, pre_cnt)

    url = m.send(lambda file_path, display_name: print('*', end='', flush=True))

    print(f"Report Url for comparing assignments and {prev_assignment_group}: " + url)

    Path(output_path).mkdir(parents=True, exist_ok=True)

    # Save report file
    m.saveWebPage(url, os.path.join(output_path, 'report.html'))

    # Download whole report locally including code diff links
    mosspy.download_report(url, os.path.join(output_path, 'report'), connections=8, log_level=10)


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    conf = load_config(args.config)
    config = DEFAULT_CONFIG.copy()
    config.update(conf)

    if args.output is not None:
        config['output'] = args.output

    moss_options = DEFAULT_MOSS_OPTIONS.copy()
    if 'moss_options' in config:
        moss_options.update(config['moss_options'])
        del config['moss_options']

    output_path = config['output']
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    files_path = config['output']
    if not os.path.exists(files_path):
        os.makedirs(files_path)

    lang = config['lang']
    branch = config['assignment_branch']
    assignment_path = config['assignment_path']
    assignment_files = config['assignment_files']
    this_quarter_groups = config['this_quarter_groups']
    previous_quarter_groups = config['previous_quarter_groups']
    base_repos = config['base_repos']
    base_files = config['base_files']

    base_path = os.path.join(output_path, 'base')

    if this_quarter_groups is None:
        this_quarter_groups = []

    if not args.no_git_clone:
        setup_files(this_quarter_groups + previous_quarter_groups, files_path, branch=branch)
        for i, base_repo in enumerate(base_repos):
            clone_repo(base_repo, base_path, f'base_{i}')

    base_file_paths = []
    for base_file in base_files:
        base_file_paths += get_files(base_path, base_file)

    for assignment_file in assignment_files:
        print(f'Comparing {assignment_file} files:')
        assignment_file_paths = []
        for group in this_quarter_groups:
            group_path = os.path.join(files_path, group)
            assignment_file_paths += get_files(group_path, assignment_file, assignment_path=assignment_path)
        remaining = file_num_limit - len(assignment_file_paths)
        for group in previous_quarter_groups:
            print(f'\tComparing with {group}')
            group_path = os.path.join(files_path, group)
            prev_assignment_file_paths = get_files(group_path, assignment_file, assignment_path=assignment_path)
            for i in range(math.ceil(len(prev_assignment_file_paths)/remaining)):
                start = i*remaining
                end = min(len(prev_assignment_file_paths), (i + 1)*remaining)
                name = f'{assignment_file}_{group}_part{i}_reports'
                report_path = os.path.join(output_path, name)
                run_moss(report_path, lang, moss_options, base_file_paths, assignment_file_paths, group,
                         prev_assignment_file_paths[start:end], name, exclude=files_path)
                time.sleep(config['moss_request_cooldown'])


if __name__ == '__main__':
    main()
