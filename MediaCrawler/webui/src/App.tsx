import { useEffect, useState } from 'react'
import { ResearchAssistant } from '@/components/ResearchAssistant'
import { Toaster } from 'sonner'
import { Sidebar } from '@/components/layout/Sidebar'
import { MainContent } from '@/components/layout/MainContent'
import { CrawlerConfigPanel } from '@/components/config/CrawlerConfigPanel'
import { EnvironmentCheck, isEnvChecked } from '@/components/env/EnvironmentCheck'
import { LicenseDisclaimer, isLicenseAccepted } from '@/components/license/LicenseDisclaimer'

function App() {
  const [assistant, setAssistant] = useState(!location.hash.startsWith('#crawler'))
  useEffect(() => {
    const changed = () => setAssistant(!location.hash.startsWith('#crawler'))
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  // Initialize by checking localStorage if license has been accepted
  const [licenseAccepted, setLicenseAccepted] = useState(() => isLicenseAccepted())
  // Initialize by checking localStorage if env check has passed
  const [envChecked, setEnvChecked] = useState(() => isEnvChecked())
  // State for showing disclaimer manually
  const [showDisclaimer, setShowDisclaimer] = useState(false)

  const handleEnvCheckComplete = () => {
    setEnvChecked(true)
  }

  const handleLicenseAccept = () => {
    setLicenseAccepted(true)
    setShowDisclaimer(false)
  }

  const handleShowDisclaimer = () => {
    setShowDisclaimer(true)
  }

  return (
    <div className="flex flex-col h-screen cyber-grid overflow-hidden relative">
      {/* License Disclaimer Modal - Shows first or when triggered */}
      {(!licenseAccepted || showDisclaimer) && (
        <LicenseDisclaimer onAccept={handleLicenseAccept} />
      )}

      {/* Environment Check Modal - Shows after license accepted */}
      {licenseAccepted && !showDisclaimer && !envChecked && (
        <EnvironmentCheck onCheckComplete={handleEnvCheckComplete} />
      )}

      {/* Header Bar */}
      <Sidebar onShowDisclaimer={handleShowDisclaimer} />
      <nav aria-label="功能导航" className="flex items-center gap-4 px-4 py-2 shrink-0">
        <a href="#assistant" aria-current={assistant ? 'page' : undefined} className={'rounded px-3 py-2 ' + (assistant ? 'bg-cyan-100 text-slate-900 font-semibold' : '')}>社区研究助手</a>
        <details className="ml-auto text-sm"><summary className="cursor-pointer">高级</summary>
          <a href="#crawler" aria-current={!assistant ? 'page' : undefined} className="block rounded px-3 py-2 underline" onClick={event => event.currentTarget.closest('details')?.removeAttribute('open')}>高级手动采集</a>
        </details>
      </nav>

      {/* Main Area */}
      {assistant ? <ResearchAssistant /> : <div className="flex-1 flex flex-col gap-4 p-4 overflow-hidden min-h-0">
        {/* Config Panel - Primary Action Area (Always Expanded) */}
        <div className="flex-shrink-0">
          <CrawlerConfigPanel />
        </div>

        {/* Console - Collapsible Terminal */}
        <MainContent />
      </div>}

      {/* Toast notifications - Theme-aware style */}
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'glass-panel font-mono text-cyber-text-primary',
          style: {
            fontFamily: 'JetBrains Mono, monospace',
          },
        }}
      />
    </div>
  )
}

export default App
