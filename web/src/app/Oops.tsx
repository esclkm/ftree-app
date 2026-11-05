// Ошибка на странице — вместо служебного экрана React Router: понятная фраза и кнопка «Обновить». Подробности — в консоли.
import {useRouteError} from 'react-router'
import {useT} from './i18n'

export function Oops() {
  const t = useT(), err = useRouteError()
  console.error(err)
  return <section className="card status oops">
    <p>{t('oops')}</p>
    <button className="btn tonal" onClick={() => location.reload()}>{t('oops_reload')}</button>
  </section>
}
