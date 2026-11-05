// Приложение: маршруты, хранилище. Загружается из main.tsx, когда данные уже переданы (data.ts, provide).
// Адреса — /<язык>/…, как у нынешних страниц, только без .html; старые ссылки перенаправляет LangRoot.
import {StrictMode} from 'react'
import type {SiteIndex} from '../data/schema.gen'
import {api} from './api'
import {createRoot} from 'react-dom/client'
import {Provider} from 'react-redux'
import {createBrowserRouter, Navigate, RouterProvider} from 'react-router'
import '../styles/main.scss'
import './app.scss'
import './notes/notes.scss'
import {LangRoot} from './LangRoot'
import {Oops} from './Oops'
import {AlbumPage, GalleryIndex} from './pages/Gallery'
import {Lifelines} from './pages/Lifelines'
import {Home, People, Sources} from './pages/Lists'
import {DocPage, NotFound, PlacePage, ResearchPage, ReviewPage, SourcePage} from './pages/OtherPages'
import {TreePage} from './pages/Legacy'
import {MapPage} from './pages/MapPage'
import {PersonPage} from './pages/PersonPage'
import {NewsPage, ProgressPage} from './pages/Progress'
import {Settings} from './pages/Settings'
import {makeStore} from './store'
import {Review} from './notes/Review'


// все страницы — под /:lang/ (LangRoot); адрес без языка LangRoot перенаправляет
const router = createBrowserRouter([
  {path: '/', element: <LangRoot />, errorElement: <Oops />},
  {path: '/:lang', element: <LangRoot />, errorElement: <Oops />, children: [{errorElement: <Oops />, children: [  // ошибка страницы — на её месте, меню остаётся
    {index: true, element: <Home />},
    {path: 'people', element: <People />},
    {path: 'people/:slug', element: <PersonPage />},
    {path: 'places/:slug', element: <PlacePage />},
    {path: 'sources', element: <Sources />},
    {path: 'sources/next', element: <ResearchPage />},  // «Что ещё искать» — до sources/:slug
    {path: 'sources/review', element: <ReviewPage />},  // «Сверка» — возможные связи для проверки
    {path: 'sources/:slug', element: <SourcePage />},
    {path: 'docs/:id', element: <DocPage />},  // заметка проекта; старые адреса docs/<номер>.html — сюда же (LangRoot)
    {path: 'gallery', element: <GalleryIndex />},  // «Хроника»: вкладки Места / Дома / События
    {path: 'gallery/houses', element: <GalleryIndex tab="houses" />},  // до gallery/:slug
    {path: 'gallery/events', element: <GalleryIndex tab="events" />},
    {path: 'gallery/:slug', element: <AlbumPage />},
    {path: 'tree', element: <TreePage />},
    {path: 'map', element: <MapPage />},
    {path: 'map/houses', element: <Navigate to="../gallery/houses" replace />},  // старый адрес «Домов»
    {path: 'lifelines', element: <Lifelines />},
    {path: 'progress', element: <ProgressPage />},  // «Состояние дерева»: цифры по родам
    {path: 'news', element: <NewsPage />},  // «Что нового»: правки по дням
    {path: 'settings', element: <Settings />},  // кто я, поколения в дереве, язык
    {path: 'review', element: <Review />},  // разбор фото — только в режиме заметок (notes/)
    {path: '*', element: <NotFound />},
  ]}]},
  {path: '*', element: <LangRoot />},
])

export function mount(index: SiteIndex): void {
  const store = makeStore()
  store.dispatch(api.util.upsertQueryData('index', undefined, index))  // уже скачан — второй раз не просим
  createRoot(document.getElementById('root')!).render(
    <StrictMode><Provider store={store}><RouterProvider router={router} /></Provider></StrictMode>,
  )
}
