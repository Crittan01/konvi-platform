import Link from 'next/link'

export type TabDef = {
  id: string
  label: string
  Icon: React.ElementType
  comingSoon?: boolean
}

type Props = {
  basePath: string  // e.g. "/dashboard/integrations/wompi"
  tabs: TabDef[]
  activeTab: string
}

export default function PanelTabs({ basePath, tabs, activeTab }: Props) {
  return (
    <div className="border-b border-border">
      <nav className="-mb-px flex gap-1 overflow-x-auto" aria-label="Tabs">
        {tabs.map(t => {
          const Icon = t.Icon
          const isActive = activeTab === t.id
          return (
            <Link
              key={t.id}
              href={`${basePath}?tab=${t.id}`}
              scroll={false}
              className={
                'inline-flex items-center gap-2 whitespace-nowrap border-b-2 px-3 sm:px-4 py-2.5 text-sm font-medium transition-colors ' +
                (isActive
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30')
              }
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
              {t.comingSoon && (
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                  próx
                </span>
              )}
            </Link>
          )
        })}
      </nav>
    </div>
  )
}
