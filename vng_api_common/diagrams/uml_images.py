import os

import yaml
from docutils import nodes
from docutils.parsers.rst import Directive, directives

from vng_api_common.diagrams.generate_graphs import generate_model_graphs


class UmlImagesDirective(Directive):
    has_content = False

    option_spec = {
        "apps": directives.unchanged,
        "grouped_apps": directives.unchanged,
        "excluded_models": directives.unchanged,
    }

    def run(self):
        apps = self.options.get("apps", "").split()
        grouped_apps = yaml.safe_load(self.options.get("grouped_apps", ""))
        excluded_models = self.options.get("excluded_models", "").split()

        env = self.state.document.settings.env
        static_dir = os.path.join(env.app.srcdir, "_static", "uml")

        generate_model_graphs(
            env.app,
            apps=apps,
            excluded_models=excluded_models,
            grouped_apps=grouped_apps,
        )

        if not os.path.isdir(static_dir):
            return [
                nodes.warning(
                    "", nodes.paragraph(text="_static/uml directory not found")
                )
            ]

        image_nodes = []
        for filename in sorted(os.listdir(static_dir)):
            if filename.lower().endswith(".png"):
                image_path = f"/_static/uml/{filename}"
                title_text = os.path.splitext(filename)[0].capitalize()

                title_node = nodes.subtitle(text=title_text)
                image_nodes.append(title_node)

                image_node = nodes.image(uri=image_path)
                image_node["classes"].append("uml-diagram")
                image_node["width"] = "600px"
                image_nodes.append(image_node)

        return image_nodes


def setup(app):
    app.add_directive("uml_images", UmlImagesDirective)
