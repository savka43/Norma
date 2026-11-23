import type { CSSProperties } from 'react'
import type { TemplateParameters } from '../../shared/api/types'

export function templateVariables(
  parameters: TemplateParameters,
): CSSProperties {
  const { margins } = parameters
  const [width, height] =
    parameters.orientation === 'portrait' ? [210, 297] : [297, 210]
  const variables: Record<string, string | number> = {
    '--sheet-width': `${width}mm`,
    '--sheet-height': `${height}mm`,
    '--margin-left': `${margins.left_mm}mm`,
    '--margin-right': `${margins.right_mm}mm`,
    '--margin-top': `${margins.top_mm}mm`,
    '--margin-bottom': `${margins.bottom_mm}mm`,
  }
  const styles = {
    body: parameters.body,
    caption: parameters.caption,
    list: parameters.list,
    table: parameters.table,
    ...Object.fromEntries(
      parameters.headings.map((style, index) => [`h${index + 1}`, style]),
    ),
  }
  for (const [name, style] of Object.entries(styles)) {
    const prefix = `--${name}-`
    variables[prefix + 'family'] =
      `${JSON.stringify(style.font_family)}, "Times New Roman", serif`
    variables[prefix + 'size'] = `${style.font_size_pt}pt`
    variables[prefix + 'line'] = style.line_spacing
    variables[prefix + 'indent'] = `${style.first_line_indent_mm}mm`
    variables[prefix + 'before'] = `${style.space_before_pt}pt`
    variables[prefix + 'after'] = `${style.space_after_pt}pt`
    variables[prefix + 'align'] = style.alignment
    variables[prefix + 'weight'] = style.bold ? 700 : 400
    variables[prefix + 'italic'] = style.italic ? 'italic' : 'normal'
  }
  return variables as CSSProperties
}
