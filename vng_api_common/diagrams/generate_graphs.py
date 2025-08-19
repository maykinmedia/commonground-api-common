import os

from django.core.management import call_command


def generate_model_graphs(
    app,
    apps,
    grouped_apps=None,
    excluded_models=None,
    output_dirname="_static/uml",
):
    """
    Generate UML diagrams for Django models.

    :param app: Sphinx app (provides srcdir).
    :param apps: List of apps to generate diagrams for. If None, will autodetect
                 inside components_dir.
    :param grouped_apps: Dict of {group_name: [apps]} to generate grouped diagrams.
    :param excluded_models: List of models to exclude.
    :param output_dirname: Subdir (relative to app.srcdir) where UMLs are stored.
    :param components_dir: Path to Django components (must be provided if apps=None).
    """
    output_dir = os.path.join(app.srcdir, output_dirname)
    os.makedirs(output_dir, exist_ok=True)

    exclude_models_str = ",".join(excluded_models or [])

    # grouped apps
    if grouped_apps:
        for group_name, app_list in grouped_apps.items():
            png_path = os.path.join(output_dir, f"{group_name}.png")
            try:
                call_command(
                    "graph_models",
                    *app_list,
                    output=png_path,
                    rankdir="LR",
                    hide_edge_labels=True,
                    exclude_models=exclude_models_str,
                )
                print(f"Generated grouped diagram for {group_name}")
            except Exception as exc:
                print(f"Failed to generate PNG for {group_name}: {exc}")

    # individual apps
    grouped = set(app for group in (grouped_apps or {}).values() for app in group)
    for django_app in apps:
        if django_app in grouped:
            continue

        png_path = os.path.join(output_dir, f"{django_app}.png")
        try:
            call_command(
                "graph_models",
                django_app,
                output=png_path,
                rankdir="LR",
                hide_edge_labels=True,
                exclude_models=exclude_models_str,
            )
            print(f"Generated diagram for {django_app}")
        except Exception as exc:
            print(f"Failed to generate PNG for {django_app}: {exc}")
