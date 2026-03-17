import { createApp, ref, watch } from 'Vue'
import * as Codex from '@wikimedia/codex'
import '@wikimedia/codex/dist/codex.style.css'

;(window as any).Vue = { createApp, ref, watch }
;(window as any).Codex = Codex
