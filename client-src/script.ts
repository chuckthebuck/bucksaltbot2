import * as Codex from '@wikimedia/codex'
import '@wikimedia/codex/dist/codex.style.css'

/*
Expose Codex globally so existing code like
Codex.lookup(...) works.
*/
;(window as any).Codex = Codex

window.addEventListener('load', () => {
    console.log('Buckbot UI loaded')
})
