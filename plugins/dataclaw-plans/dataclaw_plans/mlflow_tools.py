"""MLflow experiment tracking tools."""

from __future__ import annotations

import logging
from typing import Any

from dataclaw.config.paths import plugin_data_dir

logger = logging.getLogger(__name__)

_TRACKING_URI: str | None = None


def _get_tracking_uri() -> str:
    global _TRACKING_URI
    if _TRACKING_URI is None:
        db_path = plugin_data_dir("plans") / "mlflow.db"
        _TRACKING_URI = f"sqlite:///{db_path}"
    return _TRACKING_URI


def _client():
    import mlflow
    mlflow.set_tracking_uri(_get_tracking_uri())
    return mlflow.tracking.MlflowClient(_get_tracking_uri())


def get_or_create_experiment(session_id: str) -> str:
    """Get or create an MLflow experiment for a session."""
    client = _client()
    exp_name = f"dataclaw-{session_id}"
    exp = client.get_experiment_by_name(exp_name)
    if exp:
        return exp.experiment_id
    artifacts_dir = str(plugin_data_dir("plans") / "mlflow_artifacts")
    return client.create_experiment(exp_name, artifact_location=artifacts_dir)


def _serialize(val: Any) -> Any:
    if val is None or isinstance(val, (int, float, str, bool)):
        return val
    return str(val)


async def query_mlflow_runs(
    *,
    session_id: str = "",
    **kw: Any,
) -> dict[str, Any]:
    """Query MLflow runs for a session."""
    if not session_id:
        return {"runs": [], "error": "session_id required"}

    try:
        client = _client()
        exp_name = f"dataclaw-{session_id}"
        exp = client.get_experiment_by_name(exp_name)
        if not exp:
            return {"runs": [], "experiment": None}

        from mlflow.entities import ViewType
        runs = client.search_runs(
            experiment_ids=[exp.experiment_id],
            order_by=["start_time DESC"],
            max_results=50,
            run_view_type=ViewType.ACTIVE_ONLY,
        )

        result = []
        for run in runs:
            # List artifacts for this run
            artifacts = []
            try:
                for artifact in client.list_artifacts(run.info.run_id):
                    artifacts.append({"path": artifact.path, "size": artifact.file_size, "is_dir": artifact.is_dir})
            except Exception:
                pass

            # Get dataset inputs if available
            datasets = []
            try:
                if hasattr(run, 'inputs') and run.inputs and hasattr(run.inputs, 'dataset_inputs'):
                    for ds_input in run.inputs.dataset_inputs:
                        ds = ds_input.dataset
                        datasets.append({"name": ds.name, "digest": ds.digest, "source_type": ds.source_type})
            except Exception:
                pass

            result.append({
                "run_id": run.info.run_id,
                "status": run.info.status,
                "start_time": run.info.start_time,
                "end_time": run.info.end_time,
                "params": {k: _serialize(v) for k, v in run.data.params.items()},
                "metrics": {k: _serialize(v) for k, v in run.data.metrics.items()},
                "tags": dict(run.data.tags),
                "artifacts": artifacts,
                "datasets": datasets,
            })

        return {"runs": result, "experiment_id": exp.experiment_id}
    except Exception as e:
        logger.exception("Failed to query MLflow runs")
        return {"runs": [], "error": str(e)}


async def query_mlflow_runs_for_project(
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    """Query MLflow runs across all sessions belonging to a project."""
    from dataclaw.storage.sessions import list_sessions

    sessions = await list_sessions(project_id)
    experiments: list[dict[str, Any]] = []

    for sess in sessions:
        sid = sess.get("id", "")
        if not sid:
            continue
        result = await query_mlflow_runs(session_id=sid)
        runs = result.get("runs", [])
        if runs or result.get("experiment_id"):
            experiments.append({
                "session_id": sid,
                "session_title": sess.get("title", sid[:12]),
                "experiment_id": result.get("experiment_id"),
                "runs": runs,
            })

    return experiments
