from __future__ import annotations

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import Step1Context, Step2TemplateResult


def classify_step2_template(context: Step1Context) -> Step2TemplateResult:
    kind_2 = context.representative_node.kind_2
    if kind_2 == 4:
        return Step2TemplateResult(template_class="center_junction", supported=True, reason=None)
    if kind_2 == 2048:
        return Step2TemplateResult(template_class="single_sided_t_mouth", supported=True, reason=None)
    return Step2TemplateResult(
        template_class=None,
        supported=False,
        reason=f"unsupported_kind_2:{kind_2}",
    )
