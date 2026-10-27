"""Navigation helpers for the product-card intake wizard."""
from dataclasses import replace
from .marketplace_studio import ProductProject, Stage


def back(project: ProductProject) -> ProductProject:
    if project.stage == Stage.MARKETPLACE:
        return ProductProject()
    if project.stage == Stage.REFERENCES:
        return replace(project, marketplace=None, reference_ids=(), stage=Stage.MARKETPLACE)
    if project.stage == Stage.BRIEF:
        return replace(project, stage=Stage.REFERENCES)
    if project.stage == Stage.REVIEW:
        return replace(project, stage=Stage.BRIEF)
    raise ValueError('Back navigation is not available at this stage')


def cancel() -> ProductProject:
    return ProductProject()
