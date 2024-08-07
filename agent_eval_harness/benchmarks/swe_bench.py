import subprocess
from .base_benchmark import BaseBenchmark
import json
from datasets import load_dataset
from typing_extensions import NotRequired, TypedDict, List, Dict, Optional
from pydantic.config import ConfigDict
from pydantic import TypeAdapter, ValidationError
import time
import os
import sys
from ..utils.utils import move_merge_dirs
from ..utils.weave_utils import get_total_cost, assert_task_id_logging, get_weave_calls
from datetime import datetime

class SWEBenchBenchmark(BaseBenchmark):
    def __init__(self, config):
        self.config = config
        self.dataset_name = config.get('swe_bench_dataset', 'princeton-nlp/SWE-bench_Lite')
        self.max_workers = config.get('swe_bench_max_workers', 1)
        self.benchmark_dir = os.path.join(os.path.dirname(__file__), 'SWE-bench')
        self.environment = 'swebench'
        self.benchmark_name = 'swebench_lite'

        self.benchmark = load_dataset('princeton-nlp/SWE-bench_Lite', split='test').to_list()[:1] # TODO use full benchmark after dev


    def run(self, agent_function, run_id: str) -> Dict:

        # Generate predictions using the agent function
        predictions = self._generate_predictions(agent_function, run_id)
        
        # Save predictions to a temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as temp_file:
            for pred in predictions:
                temp_file.write(json.dumps(pred) + '\n')
            predictions_path = temp_file.name

        # Run the SWE-bench evaluation harness
        result = self._run_evaluation_harness(predictions_path, run_id)

        return result

    def _generate_predictions(self, agent_function, run_id) -> List[Dict]:
        # Get prediction from agent
        agent_output = agent_function(self.benchmark)

        # Format prediction for SWE-bench
        predictions = [{'instance_id': task["instance_id"], 
                        'model_patch': task['model_patch'],
                        'model_name_or_path': run_id} for task in agent_output]

        return predictions

    def _run_evaluation_harness(self, predictions_path, run_id):

        command = (
            f"poetry run python -m swebench.harness.run_evaluation "
            f"--dataset_name {self.dataset_name} "
            f"--predictions_path {predictions_path} "
            f"--max_workers {self.max_workers} "
            f"--run_id {run_id}"
        )

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=True,
                bufsize=1,
                universal_newlines=True
            )

            stdout_output = []
            stderr_output = []

            while True:
                stdout_line = process.stdout.readline()
                stderr_line = process.stderr.readline()

                if stdout_line:
                    print(stdout_line.strip())
                    stdout_output.append(stdout_line)
                if stderr_line:
                    print(stderr_line.strip(), file=sys.stderr)
                    stderr_output.append(stderr_line)

                if stdout_line == '' and stderr_line == '' and process.poll() is not None:
                    break

            return_code = process.wait()

            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, command, 
                                                    output=''.join(stdout_output),
                                                    stderr=''.join(stderr_output))

            return self._parse_evaluation_result(run_id)


        except subprocess.CalledProcessError as e:
            print(f"Error running SWE-bench evaluation harness: {e}")
            print(f"Stdout: {e.output}")
            print(f"Stderr: {e.stderr}")
            raise


    def _parse_evaluation_result(self, run_id):
        # Load the evaluation results
        with open(f"{run_id}.{run_id}.json", 'r') as f:
            results = json.load(f)

        # delete file
        os.remove(f"{run_id}.{run_id}.json")

        return results

    def test_run(self, agent_function, weave_client):
        # Implement a simple test task for SWE-bench
        test_task = [{
                'repo': 'example/math-operations',
                'instance_id': 'math-operations-001',
                'base_commit': 'abc123',
                'patch': """
                        diff --git a/math_ops.py b/math_ops.py
                        --- a/math_ops.py
                        +++ b/math_ops.py
                        @@ -1,3 +1,3 @@
                        def operate(a, b):
                        -    return a + b
                        +    return a * b
                        ''',
                                'test_patch': '''
                        diff --git a/test_math_ops.py b/test_math_ops.py
                        --- a/test_math_ops.py
                        +++ b/test_math_ops.py
                        @@ -1,5 +1,5 @@
                        def test_operate():
                        -    assert operate(2, 3) == 5
                        -    assert operate(-1, 1) == 0
                        -    assert operate(0, 0) == 0
                        +    assert operate(2, 3) == 6
                        +    assert operate(-1, 1) == -1
                        +    assert operate(0, 0) == 0
                        """,
                'test_patch': """
                        diff --git a/test_math_ops.py b/test_math_ops.py
                        --- a/test_math_ops.py
                        +++ b/test_math_ops.py
                        @@ -1,5 +1,5 @@
                        def test_operate():
                        -    assert operate(2, 3) == 5
                        -    assert operate(-1, 1) == 0
                        +    assert operate(2, 3) == 6
                        +    assert operate(-1, 1) == -1
                            assert operate(0, 0) == 0
                        """,
                'problem_statement': "Change the operation in the 'operate' function from addition to multiplication.",
                'hints_text': "Consider changing the '+' operator to '*'.",
                'created_at': '2023-07-30T12:00:00Z',
                'version': '1.0',
                'FAIL_TO_PASS': '["test_math_ops.py::test_operate"]',
                'PASS_TO_PASS': '[]',
                'environment_setup_commit': 'def456'
            }]

        test_output = agent_function(test_task)

        # Validate agent output
        self.validate_agent_output(test_output)

        # validate that there was cost associated with the test run
        time.sleep(5) # wait to finish usage calculation on weave
        self.validate_logging(weave_client, test_weave_task_id='math-operations-001')

        return True

    @property
    def type_adapter(self):
        class Task(TypedDict):
            model_config = ConfigDict(extra='allow')
            repo: str
            instance_id: str
            base_commit: str
            patch: str
            test_patch: str
            problem_statement: str
            hints_text: str
            created_at: str
            version: str
            FAIL_TO_PASS: str
            PASS_TO_PASS: str
            environment_setup_commit: str
            model_patch: str
            model_name_or_path: str
        return TypeAdapter(List[Task])


    def process_and_upload_results(self, 
                                   agent_name: str, 
                                   run_id: str, 
                                   eval_results: Dict, 
                                   weave_client,
                                   config, 
                                   upload=False):
        # move logs/ direcotry to results/benchmark_name/logs
        os.makedirs(f"results/{self.benchmark_name}/{run_id}", exist_ok=True)
        move_merge_dirs("logs/", f"results/{self.benchmark_name}/logs/")

        # store results
        out_path = f"results/{self.benchmark_name}/{run_id}/{run_id}.json"
        with open(out_path, 'w') as f:
            json.dump(eval_results, f)        

        # New dict
        upload_dict = {
            "config": {'agent_name': agent_name, 
                       'benchmark_name': self.benchmark_name, 
                       'date': datetime.now().strftime("%Y-%m-%d"),
                       'run_id': run_id,
                       **config[self.benchmark_name]},
            "results": {
                "accuracy": eval_results['completed_instances']/eval_results['total_instances'],
                "total_cost": get_total_cost(weave_client),
            },
            "raw_eval_results": eval_results,
            "raw_logging_results": get_weave_calls(weave_client)
        }

        # Store the upload results locally
        with open(os.path.join(out_path, f"{run_id}_UPLOAD.json"), 'w') as f:
            json.dump(upload_dict, f)

        if upload:
            self.upload_results(run_id, upload_dict)


        return upload_dict['results']

        