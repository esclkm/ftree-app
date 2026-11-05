// Настройки тестов (vitest). Сборка приложения — vite.app.config.ts (npm run build:app; её зовёт сборщик сайта
// scripts/site.mjs). Отдельных скриптов на каждую страницу больше нет: все страницы рисует приложение (05.11.2026).
/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import {defineConfig} from 'vite'

export default defineConfig({
  plugins: [react()],
  // тесты — на данных вымышленного образца (test/sampleSite.mjs), не на собранном сайте нашего дерева
  test: {globalSetup: ['test/sampleSite.mjs']},
})
