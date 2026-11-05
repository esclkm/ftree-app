// Что test/sampleSite.mjs передаёт тестам (данные сайта вымышленного образца)
import type {UiFile} from '../src/data/schema.gen'

declare module 'vitest' {
  export interface ProvidedContext {
    sampleData: string
    sampleUi: UiFile
  }
}
