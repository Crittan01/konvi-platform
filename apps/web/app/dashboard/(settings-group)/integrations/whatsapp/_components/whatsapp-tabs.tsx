import { Settings, FileText, Activity, UserX } from 'lucide-react'
import PanelTabs, { TabDef } from '../../_components/panel-tabs'

export const WHATSAPP_TABS: TabDef[] = [
  { id: 'setup',       label: 'Setup',       Icon: Settings },
  { id: 'plantillas',  label: 'Plantillas',  Icon: FileText },
  { id: 'calidad',     label: 'Calidad',     Icon: Activity },
  { id: 'optouts',     label: 'Opt-outs',    Icon: UserX },
]

type Props = {
  activeTab: string
}

export default function WhatsAppTabs({ activeTab }: Props) {
  return (
    <PanelTabs
      basePath="/dashboard/integrations/whatsapp"
      tabs={WHATSAPP_TABS}
      activeTab={activeTab}
    />
  )
}
