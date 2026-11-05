// Приложение сайта (одна страница на все адреса: /<язык>/people/<slug>, /<язык>/places/<slug> …). npm run build:app —
// сборка в dist-app/ (её берёт сборщик сайта scripts/site.mjs); npm run app — сервер разработки: http://localhost:5173/ru/
// Данные, фото и файлы — из папки выгрузки (FTREE_SITE_EXPORT, по умолчанию ../4_outputs/site_export: rodo site export).
import react from '@vitejs/plugin-react'
import {createReadStream, existsSync, statSync} from 'node:fs'
import {extname, join, normalize} from 'node:path'
import {defineConfig, type Plugin} from 'vite'

const SITE = process.env.FTREE_SITE_EXPORT ?? join(__dirname, '..', '4_outputs', 'site_export')
const SHARED = ['/data/', '/media/', '/files/']  // как на хостинге — от корня
const TYPES: Record<string, string> = {'.json': 'application/json; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.pdf': 'application/pdf', '.m4a': 'audio/mp4'}

/** Отдаёт из папки выгрузки то, что приложение читает от корня. Файла нет — 404 (на хостинге было бы 200 и главная). */
function site(): Plugin {
  return {
    name: 'ftree-site-files',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = decodeURIComponent((req.url ?? '').split('?')[0])
        if (!SHARED.some(p => path.startsWith(p))) return next()
        const file = normalize(join(SITE, path))
        if (!file.startsWith(SITE) || !existsSync(file) || !statSync(file).isFile()) { res.statusCode = 404; res.end(); return }
        res.setHeader('Content-Type', TYPES[extname(file).toLowerCase()] ?? 'application/octet-stream')
        createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  base: '/',
  plugins: [react(), site()],
  build: {outDir: 'dist-app', emptyOutDir: true, target: 'es2020'},
})
