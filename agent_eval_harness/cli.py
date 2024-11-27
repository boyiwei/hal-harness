import os
import click
import yaml
import asyncio
from typing import Any, Dict

from .agent_runner import AgentRunner
from .inspect.inspect import is_inspect_benchmark
from .inspect_runner import inspect_evaluate
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.option(
    "--agent_name",
    required=True,
    help="Name of the agent you want to add to the leaderboard",
)
@click.option(
    "--agent_function",
    required=False,
    help="Path to the agent function. Example: agent.agent.run",
)
@click.option("--agent_dir", required=False, help="Path to the agent directory.")
@click.option(
    "-A",
    multiple=True,
    type=str,
    help="One or more args to pass to the agent (e.g. -A arg=value)",
)
@click.option("--benchmark", required=True, help="Name of the benchmark to run")
@click.option(
    "-B",
    multiple=True,
    type=str,
    help="One or more args to pass to the benchmark (e.g. -B arg=value)",
)
@click.option("--upload", is_flag=True, help="Upload results to HuggingFace")
@click.option("--max_concurrent", default=10, help="Maximum agents to run for this benchmark")
@click.option("--conda_env_name", help="Conda environment to run the custom external agent in if run locally")
@click.option("--model", default="gpt-4o-mini", help="Backend model to use")
@click.option("--run_id", help="Run ID to use for logging")
@click.option(
    "--config",
    default=os.path.join(os.path.dirname(__file__), "config.yaml"),
    help="Path to configuration file",
)
@click.option("--vm", is_flag=True, help="Run the agent on an azure VM")
@click.option("--continue_run", is_flag=True, help="Continue from a previous run, only running failed or incomplete tasks")
def main(
    config,
    benchmark,
    agent_name,
    agent_function,
    agent_dir,
    model,
    run_id,
    upload,
    max_concurrent,
    conda_env_name,
    continue_run,
    a,
    b,
    vm,
    **kwargs,
):
    """Run agent evaluation on specified benchmark with given model."""

    # Validate that run_id is provided when continuing a run
    if continue_run and not run_id:
        raise click.UsageError("--run_id must be provided when using --continue_run")

    # Validate required parameters
    if not agent_function:
        raise click.UsageError("--agent_function is required")
    if not agent_dir:
        raise click.UsageError("--agent_dir is required")

    # Parse agent and benchmark args
    agent_args = parse_cli_args(a)
    benchmark_args = parse_cli_args(b)

    # Add model to agent args
    agent_args['model_name'] = model

    if is_inspect_benchmark(benchmark):
        # Run the inspect evaluation
        inspect_evaluate(
            benchmark=benchmark,
            benchmark_args=benchmark_args,
            agent_name=agent_name,
            agent_function=agent_function,
            agent_dir=agent_dir,
            agent_args=agent_args,
            model=model,
            run_id=run_id,
            upload=upload or False,
            max_concurrent=max_concurrent,
            conda_env_name=conda_env_name,
            vm=vm,
            continue_run=continue_run
        )
    else:
        # Initialize agent runner
        runner = AgentRunner(
            agent_function=agent_function,
            agent_dir=agent_dir,
            agent_args=agent_args,
            benchmark_name=benchmark,
            config=config,
            run_id=run_id,
            use_vm=vm,
            max_concurrent=max_concurrent,
            conda_env=conda_env_name,
            continue_run=continue_run
        )

        # Run evaluation
        try:
            results = asyncio.run(runner.run(
                agent_name=agent_name,
                upload=upload or False
            ))
            print("\n=====Results Summary=====")
            print(f"Accuracy: {results.get('accuracy', 'N/A')}")
            print(f"Total Cost: {results.get('total_cost', 'N/A')}")
            print("=====")
        except Exception as e:
            print(f"Error running evaluation: {e}")
            raise


def parse_cli_args(args: tuple[str] | list[str] | None) -> Dict[str, Any]:
    """Parse CLI arguments into a dictionary."""
    params: Dict[str, Any] = {}
    if args:
        for arg in list(args):
            parts = arg.split("=")
            if len(parts) > 1:
                key = parts[0].replace("-", "_")
                value = yaml.safe_load("=".join(parts[1:]))
                if isinstance(value, str):
                    value = value.split(",")
                    value = value if len(value) > 1 else value[0]
                params[key] = value
    return params


if __name__ == "__main__":
    main()
