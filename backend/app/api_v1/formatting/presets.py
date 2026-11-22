from app.api_v1.formatting.schemas import Margins, TemplateParameters, TextStyle


def gost_parameters() -> TemplateParameters:
    """Editable baseline oriented to GOST 7.32-2017, not a conformity certificate."""
    body = TextStyle(
        font_family="Times New Roman",
        font_size_pt=14,
        line_spacing=1.5,
        first_line_indent_mm=12.5,
        space_before_pt=0,
        space_after_pt=0,
        alignment="justify",
        bold=False,
        italic=False,
    )
    heading = body.model_copy(
        update={
            "bold": True,
            "alignment": "left",
            "space_before_pt": 18.0,
            "space_after_pt": 12.0,
        }
    )
    return TemplateParameters(
        schema_version=1,
        page_format="A4",
        orientation="portrait",
        margins=Margins(top_mm=20, bottom_mm=20, left_mm=30, right_mm=15),
        body=body,
        headings=[heading.model_copy(deep=True) for _ in range(6)],
        caption=body.model_copy(update={"first_line_indent_mm": 0.0, "alignment": "center"}),
        list=body.model_copy(deep=True),
        table=body.model_copy(update={"first_line_indent_mm": 0.0, "line_spacing": 1.0}),
        page_number_start=1,
    )
