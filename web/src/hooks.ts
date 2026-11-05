import {useState} from 'react'

/** Число, которое браузер помнит между заходами (например, сколько поколений показывать). 0 — «все» */
export function useStoredNumber(key: string): [number, (v: number) => void] {
  const [value, setValue] = useState(() => +(localStorage.getItem(key) || 0))
  const save = (v: number) => {
    if (v) localStorage.setItem(key, String(v)); else localStorage.removeItem(key)
    setValue(v)
  }
  return [value, save]
}
