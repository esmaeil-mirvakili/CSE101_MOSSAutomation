import json
import logging
import mosspy
import os
from pathlib import Path
from queue import Queue
import shutil
import time
from tqdm import tqdm
from typing import Dict, List
from dotenv import load_dotenv


load_dotenv()
moss_userid = os.getenv('USER_ID')


class TaskResult:
    def __init__(self, success: bool, ex: Exception = None):
        self.success = success
        self.ex = ex


class MossTask:
    def __init__(self, report_path: str, identifier: str, files: List[str], base_files: List[str] = None, lang: str = 'c', file_path: str = ''):
        self.report_path = report_path
        self.file_path = file_path
        self.identifier = identifier
        if base_files is None:
            base_files = []
        self.base_files = base_files
        assert files is not None and len(files) > 0
        self.files = files
        self.lang = lang

    def run(self, moss_options: dict) -> TaskResult:
        ex = None
        self.clear()
        try:
            success = self.run_moss(moss_options)
        except Exception as e:
            success = False
            ex = e
        if not success:
            self.clear()
        return TaskResult(success=success, ex=ex)

    def run_moss(self, moss_options) -> bool:
        if moss_options is None:
            moss_options = {}

        m = mosspy.Moss(moss_userid, self.lang)

        m.options.update(moss_options)

        for base_file in self.base_files:
            m.addBaseFile(base_file)

        for file in self.files:
            display_name = file.replace(self.file_path, '')
            m.addFile(file, display_name=display_name)
        print(f'Uploading files for {self.identifier}:')
        pbar = tqdm(total=len(self.files) + len(self.base_files))

        def update_pbar(file_path, name):
            nonlocal pbar
            pbar.update(1)

        url = m.send(update_pbar)
        pbar.close()

        print(f"Report Url: " + url)
        print('Downloading the reports...')

        Path(self.report_path).mkdir(parents=True, exist_ok=True)

        # Save report file
        m.saveWebPage(url, os.path.join(self.report_path, 'report.html'))

        # Download whole report locally including code diff links
        # mosspy.download_report(url, os.path.join(self.report_path, 'report'), log_level=logging.CRITICAL)
        cnt = 0
        chars = ['|', '/', '—', '\\']
        last_print = 0
        def waiting(url):
            nonlocal cnt
            nonlocal last_print
            if time.time() - last_print < 0.5:
                return
            last_print = time.time()
            cnt = (cnt + 1) % 4
            print(f'\rDownloading report files {chars[cnt]}', end='')

        mosspy.download_report(url, os.path.join(self.report_path, 'report'), connections=8, log_level=logging.INFO, on_read=waiting)

        return True

    def clear(self):
        if os.path.exists(self.report_path):
            shutil.rmtree(self.report_path)

    @property
    def info(self) -> dict:
        return {
            'identifier': self.identifier,
            'report_path': self.report_path,
            'base_files': self.base_files,
            'files': self.files,
            'lang': self.lang,
            'file_path': self.file_path
        }


class TaskState:
    def __init__(self, task: MossTask, done: bool = False):
        self.task = task
        self.done = done


class TaskManager:
    def __init__(self, output: str, task_cooldown: int = 60, resume: bool = False):
        self.output = output
        self.task_cooldown = task_cooldown
        self.state_path = os.path.join(output, 'state.json')
        self.tasks: Dict[str, TaskState] = {}
        self.q: Queue = Queue()
        if resume:
            self._load_state()
        elif os.path.exists(self.state_path):
            os.remove(self.state_path)

    def add_task(self, task: MossTask):
        self.tasks[task.identifier] = TaskState(task)
        self.q.put(task)
        self._save_state()

    def _mark_task_as_done(self, task_id: str):
        assert not self.tasks[task_id].done
        self.tasks[task_id].done = True
        self._save_state()

    def _save_state(self):
        state = {
            'tasks': {
                task_state.task.identifier: {'done': task_state.done,
                                             'info': task_state.task.info} for task_state in self.tasks.values()
            }
        }
        with open(self.state_path, 'w') as state_file:
            json.dump(state, state_file)

    def _load_state(self):
        if not os.path.exists(self.state_path):
            return
        self.tasks = {}
        self.q = Queue()
        with open(self.state_path, 'r') as state_file:
            state = json.load(state_file)
            for task_id, task_data in state['tasks'].items():
                task_done = task_data['done']
                task_info: dict = task_data['info']
                task = MossTask(**task_info)
                task_state = TaskState(task, task_done)
                self.tasks[task_id] = task_state
                self.q.put(task)

    def run(self, moss_options=None):
        while not self.q.empty():
            task = self.q.get()
            try:
                if self.tasks[task.identifier].done:
                    continue
                print(f'Running task {task.identifier}:')
                task_result: TaskResult = task.run(moss_options)
                if task_result.success:
                    self._mark_task_as_done(task.identifier)
                    print(f'Task {task.identifier} successfully done...')
                else:
                    print(f'Task {task.identifier} failed...')
                if task_result.ex is not None:
                    raise task_result.ex
            except Exception as ex:
                print(f'Error at handling task {task.identifier}:')
                print(ex)
            print(f'Waiting for {self.task_cooldown} secs...')
            time.sleep(self.task_cooldown)
        print('All tasks are done.')
