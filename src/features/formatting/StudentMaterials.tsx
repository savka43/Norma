import { Panel, Button } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import {
  TemplatePicker,
  TemplateSummary,
  useTemplatePicker,
} from './TemplatePicker'

export function StudentMaterials() {
  const picker = useTemplatePicker(true)
  return (
    <div className={w.page}>
      <h1>Материалы</h1>
      <Panel title="Шаблоны оформления">
        <div className={w.form}>
          <TemplatePicker picker={picker} />
          {picker.templates.error && (
            <Button onClick={() => void picker.templates.refetch()}>
              Повторить загрузку шаблонов
            </Button>
          )}
          {picker.versions.error && (
            <Button onClick={() => void picker.versions.refetch()}>
              Повторить загрузку версий
            </Button>
          )}
          {picker.version && <TemplateSummary version={picker.version} />}
        </div>
      </Panel>
    </div>
  )
}
