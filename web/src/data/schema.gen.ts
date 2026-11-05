// Создано scripts/schema-types.mjs из web/schema/*.schema.json — не править руками: npm run schema

/**
 * Номер карточки в дереве (cr_id). Номер важнее имени: все связи — по нему.
 */
export type Id = string;
/**
 * Кусок адреса страницы латиницей: /people/<slug>. У тёзок разный (ivan-yasenev, ivan-yasenev-pfa).
 */
export type Slug = string;
export type Lang = "ru" | "pl" | "es" | "en";
/**
 * Откуда знаем: семья > найдено > чужое дерево > вывод проекта. Факт только из чужого дерева — подсказка для проверки.
 */
export type Provenance = "family" | "found" | "other_tree" | "inference";
/**
 * Насколько уверены. Три слова и ничего больше (GEDCOM X: High / Medium / Low). Почему так — в reasoning.
 */
export type Confidence = "high" | "normal" | "low";
export type DocId = string;

export interface SiteData {
  index: SiteIndex;
  person: PersonFile;
  place: PlaceFile;
  source: SourceFile;
  ui: UiFile;
  gallery: GalleryFile;
  research: ResearchFile;
  review: ReviewFile;
  progress: ProgressFile;
  doc: DocFile;
  site: SiteFile;
}
/**
 * Лёгкий список всех для поиска, дерева, «кем приходится» и карты. Заменяет tree_data.js, kin_data.js и map_data.js: один человек — одна запись, разводы — один раз. Всё подробное — в файле человека.
 */
export interface SiteIndex {
  schema: "index/1";
  built: string;
  start: Id;
  people: {
    id: Id;
    slug: Slug;
    names: LangText;
    sex: "M" | "F";
    /**
     * Годы для подписи: «1902–1986», «1921–?».
     */
    life: string;
    tree?: "pavel" | "vika" | "argentina";
    lineage?: string[];
    avatar?: string;
    /**
     * @maxItems 2
     */
    parents: [] | [Id] | [Id, Id];
    spouses: Id[];
    children: Id[];
    /**
     * Сколько материала — значки на карточке.
     */
    stats?: {
      bio: boolean;
      texts: number;
      facts: number;
      fam: number;
      web: number;
      tree: number;
      pics: number;
      langs: Lang[];
    };
    /**
     * Инициалы для круга без фото, по языкам («СМ»); у неизвестного — null (рисуем значок).
     */
    initials?: LangText | null;
    /**
     * Цвет круга без фото, 0–7 — всегда один для человека (от номера).
     */
    color?: number;
    /**
     * От какого брака родителей ребёнок: 0 — один брак, 1, 2 … — номер (цвет линий на дереве).
     */
    marriage?: number;
    /**
     * Насколько связь с деревом доказана (поле kinship карточки): proven — документом, likely — вероятно, possible — возможно, unlikely — маловероятно, no — не родня. Нет поля в карточке — оценка по фактам (cards/kinship.py). В дереве — цвет рамки карточки.
     */
    kinship?: "proven" | "likely" | "possible" | "unlikely" | "no";
    /**
     * Откуда уровень kinship: card — поставлен в карточке, facts — оценён по фактам и источникам.
     */
    kinship_by?: "card" | "facts";
    /**
     * Имя неизвестно («Unknown …»): в дереве есть, в списках и поиске — нет.
     */
    unknown?: boolean;
  }[];
  /**
   * Разведённые пары: «id1|id2» (по алфавиту) → год или пусто.
   */
  divorces: {
    [k: string]: string;
  };
  places: {
    id: Id;
    slug: Slug;
    names: LangText;
    lat?: number;
    lng?: number;
    /**
     * Сколько людей связано с местом.
     */
    people: number;
    type?:
      | "country"
      | "region"
      | "district"
      | "city"
      | "town"
      | "village"
      | "locality"
      | "street"
      | "house"
      | "cemetery"
      | "church"
      | "hospital"
      | "school"
      | "university"
      | "river"
      | "other";
    parent?: Id;
    /**
     * Только у дома — для раздела «Дома» на карте.
     */
    house?: {
      /**
       * Что за жильё: private — свой дом, apartment — квартира, barrack — барак, dorm — общежитие, hut — хата, изба (надписи — house_<вид>).
       */
      kind?: "private" | "apartment" | "barrack" | "dorm" | "hut";
      from?: number;
      to?: number;
      /**
       * Сколько людей в нём жило (по событиям).
       */
      residents: number;
    };
  }[];
  sources: {
    id: Id;
    slug: Slug;
    title: string;
    /**
     * Название на других языках (3_research/tree/translations/<язык>/sources/<Имя карточки>.md); нет — русское.
     */
    titles?: {
      pl?: string;
      es?: string;
      en?: string;
    };
    provenance: Provenance;
  }[];
  /**
   * Ветки рода по числу людей; «Без ветки» — последней.
   */
  branches: {
    /**
     * Как в lineage карточек.
     */
    key: string;
    slug: Slug;
    names: LangText;
    people: number;
  }[];
}
/**
 * Одна надпись на языках сайта. Русский обязателен — он основной; остальные, если есть.
 */
export interface LangText {
  ru: string;
  pl?: string;
  es?: string;
  en?: string;
}
/**
 * Всё, что показывает страница одного человека. Собирается из карточки 3_research/tree/people/<Имя>.md и его биографии. Связи — отдельными записями, как Relationship в GEDCOM X.
 */
export interface PersonFile {
  schema: "person/1";
  id: Id;
  slug: Slug;
  identifiers?: Identifiers;
  /**
   * Чьё дерево.
   */
  tree?: "pavel" | "vika" | "argentina";
  names: {
    display: LangText;
    /**
     * Как его звали дома: «дед Прокоп». Как сказано — не исправляем.
     */
    home?: string[];
    /**
     * Другие написания: в документах, у родни за границей.
     */
    aliases?: string[];
    /**
     * Фамилия выведена, а не взята из документа.
     */
    surname_inferred?: boolean;
  };
  sex: "M" | "F";
  born?: LifeEvent;
  died?: LifeEvent;
  occupation?: string;
  /**
   * «Занятие» на других языках (translations/<язык>/facts/<Имя карточки>.md).
   */
  occupation_tr?: {
    pl?: string;
    es?: string;
    en?: string;
  };
  /**
   * Все связи, где он участвует. parent — кто родитель, child — чей ребёнок; couple — супруги.
   */
  relationships: (
    | {
        type: "parent-child";
        parent: Id;
        child: Id;
      }
    | {
        type: "couple";
        person1: Id;
        person2: Id;
        /**
         * Развод; true — был, года не знаем.
         */
        divorced?: GDate | true;
      }
  )[];
  /**
   * Возможные связи — подозрение, не доказано: «возможно, тот же человек» (maybe_same) и «возможно, родня» (maybe_kin) из карточки, с обеих сторон. На дереве не рисуются. Проверенное «нет» (not_same, not_kin) сюда не попадает.
   */
  possible?: {
    /**
     * same — возможно, это один человек; kin — возможно, родня.
     */
    type: "same" | "kin";
    person: Id;
    /**
     * У kin: кем person приходится этому человеку (pibling — дядя или тётя, nibling — племянник или племянница). Пол — у person.
     */
    relation?:
      | "parent"
      | "child"
      | "sibling"
      | "pibling"
      | "nibling"
      | "cousin"
      | "grandparent"
      | "grandchild"
      | "spouse"
      | "kin";
    /**
     * На чём держится — строка из карточки (Markdown).
     */
    reason?: string;
  }[];
  /**
   * Наша работа с человеком, а не он сам.
   */
  research?: {
    priority?: "P1" | "P2" | "P3" | "P4";
    /**
     * Ветки по крови. Считает assign_lineage.py.
     */
    lineage?: string[];
    lineage_by_marriage?: string[];
    direct_ancestor?: boolean;
  };
  facts: Fact[];
  /**
   * Биография: русский текст и переводы (Markdown), линия жизни — отдельно. Контакты и адреса уже вычищены.
   */
  biography?: {
    /**
     * Откуда: путь к .md биографии в проекте.
     */
    file: string;
    /**
     * Таблица «Линия жизни» — только жизнь самого человека.
     */
    lifeline: LifelineRow[];
    /**
     * Таблица «Память» — что было после смерти: вещи в музее, книга или статья о нём, перезахоронение, мемориальная доска, посмертная реабилитация. Те же строки, что у линии жизни.
     */
    memory?: LifelineRow[];
    /**
     * «Воспоминания» — сценки, которые кто-то помнит о человеке: кто вспоминает, откуда и что. Из текста биографии раздел убран.
     */
    recollections?: Recollection[];
    /**
     * «Открытые вопросы» биографии — Markdown, ссылки по номеру; на сайте свёрнутым блоком. Из текста биографии раздел убран.
     */
    questions?: string;
    texts: {
      ru: BioText;
      pl?: BioText;
      es?: BioText;
      en?: BioText;
    };
  };
  /**
   * Где жил и в каком государстве это было тогда (считается из фактов и эпох мест).
   */
  stays?: {
    place: Id;
    from: number;
    to: number;
    /**
     * Что это за точка: ev_birth, ev_residence, ev_child, ev_death … (надписи — I18N_ROWS).
     */
    event: string;
    state?: LangText;
  }[];
  /**
   * Дома, где человек жил (жильцы домов — place.residents), по году.
   */
  homes?: {
    place: Id;
    date?: GDate;
    what: "ev_residence" | "pp_born";
  }[];
  media?: Media[];
  avatar?: Media;
  /**
   * Его документы (2_transcripts/documents): паспорт, трудовая, метрики… Закрытые (access: closed) сюда не попадают.
   */
  documents?: Document[];
  /**
   * Все источники о нём (sources карточки).
   */
  sources: Id[];
  /**
   * Где он упоминается: чужие биографии, расшифровки.
   */
  mentioned_in?: {
    title: string;
    url: string;
    person?: Id;
  }[];
  /**
   * Фото мест из жизни: снимки мест и адресов, где он был, — из тех лет, когда он там был (site_export.life_photos).
   */
  life_photos?: {
    names: LangText;
    place?: Id;
    album?: Slug;
    photos: Photo[];
  }[];
  /**
   * Адреса, где снимки есть, но не из его лет — ссылкой на место.
   */
  life_photos_other?: Id[];
}
/**
 * Номера человека в других системах (GEDCOM X identifiers).
 */
export interface Identifiers {
  /**
   * Номер MyHeritage, @I12@ без @.
   */
  gedcom_id?: string;
  gramps_id?: string;
  wikidata?: string;
}
export interface LifeEvent {
  date?: GDate;
  place?: Id;
}
/**
 * Дата, как в карточке (GEDCOM 7, шапка tools/scripts/dates.py). ru и sort считает сборщик, руками не пишутся.
 */
export interface GDate {
  /**
   * 1935 · 1935-05 · 1935-05-12 · ABT/CAL/EST/BEF/AFT 1935 · BET 1941 AND 1945 · FROM 1941 TO 1945 · FROM 1944 · TO 1950
   */
  value: string;
  /**
   * Слова источника рядом с датой: «осень», «до войны», «детство» (в GEDCOM 7 — PHRASE).
   */
  words?: string;
  /**
   * Та же дата по старому стилю, как в документе («13.06.1888»): главная дата — по новому, эта показывается рядом мелко.
   */
  os?: string;
  /**
   * Стиль, если дата до 14.02.1918 и он известен: julian — старый, gregorian — новый.
   */
  calendar?: "julian" | "gregorian";
  /**
   * Как показать по-русски: «ок. 1935», «между 1941 и 1945».
   */
  ru: string;
  /**
   * Для сортировки: ГГГГММДД первого возможного дня.
   */
  sort: number;
}
/**
 * Одна строка «Факты (с источником)» карточки. Без источника факта нет — сборка остановится.
 */
export interface Fact {
  /**
   * Вид события, если он есть (как event_type в карточках событий).
   */
  type?:
    | "birth"
    | "death"
    | "burial"
    | "marriage"
    | "divorce"
    | "residence"
    | "occupation"
    | "education"
    | "war"
    | "migration"
    | "name"
    | "custom";
  /**
   * Подпись строки, если это не дата: «Занятие», «Слова дословно».
   */
  label?: string;
  date?: GDate;
  place?: Id;
  /**
   * Markdown; ссылки на людей, места и источники — по номеру: [подпись](person:<id>), (place:<id>), (source:<id>), файл — (media:<имя файла>). Адрес страницы строит приложение. Контакты и номера домов уже вырезаны.
   */
  text: string;
  /**
   * @minItems 1
   */
  sources: [SourceRef, ...SourceRef[]];
  confidence: Confidence;
  provenance: Provenance;
  /**
   * На чём держится вывод: «1919 − 70 = 1849», «по отчеству».
   */
  reasoning?: string;
  /**
   * Перевод строки на языки сайта (3_research/tree/translations/<язык>/facts/<Имя карточки>.md). Нет языка — показываем русский.
   */
  tr?: {
    pl?: {
      label?: string;
      text: string;
      reasoning?: string;
      /**
       * Места в источниках — по порядку sources.
       */
      locators?: string[];
      /**
       * Слова при дате на этом языке («desde fines de los 60»).
       */
      when?: string;
    };
    es?: {
      label?: string;
      text: string;
      reasoning?: string;
      /**
       * Места в источниках — по порядку sources.
       */
      locators?: string[];
      /**
       * Слова при дате на этом языке («desde fines de los 60»).
       */
      when?: string;
    };
    en?: {
      label?: string;
      text: string;
      reasoning?: string;
      /**
       * Места в источниках — по порядку sources.
       */
      locators?: string[];
      /**
       * Слова при дате на этом языке («desde fines de los 60»).
       */
      when?: string;
    };
  };
}
/**
 * Ссылка на карточку источника и место в нём (GEDCOM X SourceReference).
 */
export interface SourceRef {
  source: Id;
  /**
   * Где именно: «стр. 12», «10:01», «58:04–58:27».
   */
  locator?: string;
}
export interface LifelineRow {
  /**
   * Дата, как написана в биографии: «1944 (осень)», «(без даты)».
   */
  when: string;
  date?: GDate;
  /**
   * Что было — Markdown, как у фактов.
   */
  text: string;
  /**
   * Где он был в это время — город или деревня, Markdown со ссылкой на место (колонка «Где»). На странице не показывается: по ней видно переезды.
   */
  where?: string;
  /**
   * Остальные колонки таблицы: «Источник», «Время на записи»…
   */
  extra?: {
    col: string;
    value: string;
  }[];
}
/**
 * Воспоминание — сценка, которую кто-то помнит о человеке (раздел «Воспоминания» биографии): не факт для дерева, а то, каким его видели.
 */
export interface Recollection {
  /**
   * Название сценки.
   */
  title: string;
  /**
   * Кто вспоминает и откуда: «Вспоминает [Мария](person:…), внучка · А08, 53:25». Markdown, ссылки по номеру.
   */
  by?: string;
  /**
   * Рассказ или цитата: Markdown, ссылки по номеру.
   */
  text: string;
}
export interface BioText {
  /**
   * Текст биографии: Markdown, ссылки — по номеру, как у фактов (common.schema.json, Fact.text); картинки — адрес на сайте. Линии жизни в тексте нет — она в lifeline.
   */
  md: string;
  /**
   * Перевод ИИ, человек не проверял.
   */
  ai?: boolean;
  /**
   * Русский текст поменялся после перевода.
   */
  stale?: boolean;
  /**
   * Линия жизни из перевода — на его языке (у русского текста она в biography.lifeline).
   */
  lifeline?: LifelineRow[];
  /**
   * «Память» из перевода — на его языке (у русского текста она в biography.memory).
   */
  memory?: LifelineRow[];
  /**
   * «Воспоминания» из перевода — на его языке (у русского текста они в biography.recollections).
   */
  recollections?: Recollection[];
  /**
   * «Открытые вопросы» из перевода — на его языке.
   */
  questions?: string;
}
/**
 * Фото, скан, аудио или PDF. Закрытый (private) файл без входа не отдаётся — показываем заглушку, а не битую ссылку.
 */
export interface Media {
  url: string;
  thumb?: string;
  kind: "photo" | "scan" | "audio" | "pdf";
  caption?: LangText;
  date?: GDate;
  place?: Id;
  private: boolean;
  /**
   * Лицо на общем фото: доли ширины и высоты [x1, y1, x2, y2] (GEDCOM X RectangleRegion).
   *
   * @minItems 4
   * @maxItems 4
   */
  region?: [number, number, number, number];
}
export interface Document {
  title: string;
  /**
   * Название на других языках (3_research/tree/translations/<язык>/<sources|documents>/…); нет — русское.
   */
  titles?: {
    pl?: string;
    es?: string;
    en?: string;
  };
  /**
   * Вид документа (documents.py, KINDS).
   */
  kind:
    | "metrics"
    | "civil"
    | "passport"
    | "labor"
    | "military"
    | "education"
    | "awards"
    | "personal"
    | "certificate"
    | "letter"
    | "lists"
    | "other";
  /**
   * Годы из имени файла: «1960», «1942–1945».
   */
  years: string;
  /**
   * Первая страница, маленькая копия — адрес от корня сайта.
   */
  cover?: string;
  /**
   * PDF всех страниц — адрес от корня сайта.
   */
  pdf?: string;
  doc: DocId;
  pages?: number;
  origin?: string;
  /**
   * PDF и обложка — только по паролю (документ живого или контакты в тексте).
   */
  private?: true;
}
export interface Photo {
  url: string;
  thumb: string;
  /**
   * Год для сортировки и десятилетия.
   */
  year?: number;
  /**
   * Год, как в описи: «1930-е», «ок. 1915».
   */
  year_txt?: string;
  /**
   * Что на снимке (Markdown).
   */
  desc?: string;
  /**
   * Чья это история.
   */
  whose?: string;
  /**
   * Насколько точно место.
   */
  exact?: string;
  /**
   * Под вопросом.
   */
  note?: string;
  /**
   * Откуда снимок (Markdown).
   */
  source?: string;
  rights?: string;
  link?: string;
  /**
   * Раздел описи (у тематических альбомов).
   */
  section?: string;
  era?: LangText;
  /**
   * «≈ похожее, не наше»: снята не наша деревня, а самая похожая рядом (опись — «Насколько точно», имя файла — <Настоящая>_похоже-на-<Наша>-<км>км_…). Метка — красная.
   */
  like?: {
    real?: LangText;
    ours?: LangText;
    ours_place?: Id;
    /**
     * Сколько км от нашей.
     */
    km?: number;
  };
  addr?: Id;
  /**
   * Перевод подписи (3_research/tree/translations/<язык>/photos/<имя файла>.md) — только если русская подпись с тех пор не менялась.
   */
  tr?: {
    pl?: {
      desc?: string;
      whose?: string;
      exact?: string;
      note?: string;
      section?: string;
    };
    es?: {
      desc?: string;
      whose?: string;
      exact?: string;
      note?: string;
      section?: string;
    };
    en?: {
      desc?: string;
      whose?: string;
      exact?: string;
      note?: string;
      section?: string;
    };
  };
}
/**
 * Из карточки 3_research/tree/places/<Имя>.md. Одно место — одна запись; смена государств — списком с годами (как placeref с датой в Gramps и P131 + начало/конец в Wikidata), а не копией места на каждую эпоху.
 */
export interface PlaceFile {
  schema: "place/1";
  id: Id;
  slug: Slug;
  names: LangText;
  aliases?: string[];
  type:
    | "country"
    | "region"
    | "district"
    | "city"
    | "town"
    | "village"
    | "locality"
    | "street"
    | "house"
    | "cemetery"
    | "church"
    | "hospital"
    | "school"
    | "university"
    | "river"
    | "other";
  /**
   * Настоящее место на карте (false — вымышленное или неясное).
   */
  real: boolean;
  coords?: {
    lat: number;
    lng: number;
  };
  /**
   * false — деревень с таким названием несколько, координаты под вопросом.
   */
  coords_checked?: boolean;
  parent?: Id;
  /**
   * «Государства по годам». Обязательны у места без parent (кроме реки) — иначе у людей пустые «Места и эпохи».
   */
  states?: {
    date: GDate;
    state: LangText;
    /**
     * Выделено в карточке (**Польша**) — главная эпоха для нашей истории.
     */
    main?: boolean;
  }[];
  states_from?: Id;
  media?: Media[];
  /**
   * Кто здесь родился, жил, умер.
   */
  people: Id[];
  wikidata?: string;
  /**
   * Кто связан с местом и чем: родился, жил, работал… (ключи надписей: pp_born, ev_residence …).
   */
  who?: {
    person: Id;
    what: string[];
    /**
     * Что именно было здесь и когда: событие (ключ ev_*), его даты и суть одной фразой (Markdown) — чтобы на карте было видно не просто «работа», а кем и в какие годы.
     */
    events?: {
      what: string;
      date?: GDate;
      text?: string;
    }[];
  }[];
  /**
   * Кто упоминает место ссылкой в биографии или карточке, но не родился, не умер и не жил там по событиям дерева.
   */
  mentions?: Id[];
  about?: LangText;
  /**
   * Места внутри этого (parent_place — это место): дома, больницы, деревни района.
   */
  inside?: Id[];
  /**
   * Города и деревни не дальше 150 км, ближние первыми (кроме мест выше и внутри).
   */
  nearby?: {
    place: Id;
    km: number;
  }[];
  /**
   * Места того же рода внутри того же места выше, ближние первыми; без тех, что уже в nearby.
   */
  similar?: Id[];
  /**
   * Текст карточки места (Markdown, ссылки по номеру), без «Государств по годам» и «О месте».
   */
  md?: string;
  /**
   * Перевод текста карточки места (3_research/tree/translations/<язык>/places/<Имя карточки>.md); «О месте» перевода — в about.
   */
  tr?: {
    pl?: {
      md?: string;
      /**
       * Перевод ИИ, не проверен носителем языка.
       */
      ai?: true;
      /**
       * Русский текст поменялся после перевода.
       */
      stale?: true;
    };
    es?: {
      md?: string;
      /**
       * Перевод ИИ, не проверен носителем языка.
       */
      ai?: true;
      /**
       * Русский текст поменялся после перевода.
       */
      stale?: true;
    };
    en?: {
      md?: string;
      /**
       * Перевод ИИ, не проверен носителем языка.
       */
      ai?: true;
      /**
       * Русский текст поменялся после перевода.
       */
      stale?: true;
    };
  };
  /**
   * Только у дома (type: house): что за жильё, когда построен и когда его не стало, первый и последний год, когда в нём жили наши.
   */
  house?: {
    /**
     * Что за жильё: private — свой дом, apartment — квартира, barrack — барак, dorm — общежитие, hut — хата, изба (надписи — house_<вид>).
     */
    kind?: "private" | "apartment" | "barrack" | "dorm" | "hut";
    built?: GDate;
    gone?: GDate;
    from?: number;
    to?: number;
  };
  /**
   * Кто жил в доме и когда — по событиям «место жительства» (residence) и местам рождения, по году. Только у дома.
   */
  residents?: {
    person: Id;
    date?: GDate;
    what: "ev_residence" | "pp_born";
  }[];
}
/**
 * Из карточки 3_research/tree/sources/<Название>.md (GEDCOM X SourceDescription). Сами сканы и PDF — отдельными файлами; закрытые без входа не отдаются.
 */
export interface SourceFile {
  schema: "source/1";
  id: Id;
  slug: Slug;
  title: string;
  /**
   * Название на других языках (3_research/tree/translations/<язык>/<sources|documents>/…); нет — русское.
   */
  titles?: {
    pl?: string;
    es?: string;
    en?: string;
  };
  provenance: Provenance;
  /**
   * Вид источника, как source_type в карточке (Charted Roots); book…autobiography — тексты и вырезки из sources/press (PRESS_TYPES в tools/scripts/cards/sources.py).
   */
  type:
    | "custom"
    | "vital_record"
    | "church_record"
    | "census"
    | "immigration"
    | "military"
    | "newspaper"
    | "letter"
    | "photo"
    | "audio"
    | "book"
    | "magazine"
    | "memoir"
    | "manuscript"
    | "autobiography";
  author?: string;
  repository?: string;
  date?: GDate;
  identifiers?: Identifiers;
  media?: Media[];
  /**
   * О ком этот источник.
   */
  people: Id[];
  /**
   * Текст карточки с расшифровкой (Markdown, ссылки по номеру — как у фактов).
   */
  md?: string;
  /**
   * Запись разговора в семье: на сайте — только описание, без текста и звука (site_data/privacy.py).
   */
  audio?: boolean;
}
/**
 * Надписи интерфейса на языках сайта (I18N_ROWS в tools/scripts/site_export.py) и контуры значков (Material Icons). Приложение читает их первыми.
 */
export interface UiFile {
  schema: "ui/1";
  i18n: {
    ru: {
      [k: string]: string;
    };
    pl: {
      [k: string]: string;
    };
    es: {
      [k: string]: string;
    };
    en: {
      [k: string]: string;
    };
  };
  icons: {
    [k: string]: string;
  };
}
/**
 * Альбомы снимков из 1_sources/found/photos_places (по местам) и photos_history (по темам); подписи — из описей 00_ОПИСЬ*.md. Иллюстрации «как там было», а не фото родных.
 */
export interface GalleryFile {
  schema: "gallery/1";
  albums: Album[];
}
export interface Album {
  slug: Slug;
  names: LangText;
  kind: "place" | "theme";
  place?: Id;
  about?: LangText;
  /**
   * Кто связан с местом альбома и с местами внутри него (родился, жил, умер, упомянут в биографии); с портретом — первыми. У альбома событий — о ком он (tree/albums.toml).
   */
  people?: Id[];
  photos: Photo[];
}
/**
 * План поиска по предкам из <папка поиска>/ПОИСК_ДАЛЬШЕ.md (paths.RESEARCH_NEXT): текст без заголовка, очищен от контактов, ссылки Obsidian — по номеру, как у текстов источников. Нет файла — нет и этого JSON.
 */
export interface ResearchFile {
  schema: "research/1";
  /**
   * Текст плана (Markdown, ссылки по номеру — как у фактов).
   */
  md: string;
  /**
   * Когда план правили: updated в свойствах файла, иначе время файла (ГГГГ-ММ-ДД).
   */
  updated?: string;
}
/**
 * Пары карточек для проверки руками: отмеченные в карточках (maybe_same, maybe_kin) и найденные автоматически (possible.auto: одно имя, та же фамилия или место, годы не спорят). Пары с проверенным «нет» (not_same, not_kin) сюда не попадают. Решение — командой (поле commands), сайт ничего не меняет.
 */
export interface ReviewFile {
  schema: "review/1";
  pairs: {
    /**
     * marked — подозрение записано в карточке; auto — нашёл скрипт.
     */
    source: "marked" | "auto";
    type: "same" | "kin";
    /**
     * У kin: кем b приходится a (как в person.possible).
     */
    relation?: string;
    a: Side;
    b: Side;
    /**
     * На чём держится — строка из карточки (Markdown).
     */
    reason?: string;
    /**
     * Что совпало (у найденных скриптом).
     */
    why?: string[];
    commands: {
      same: string;
      yes?: string;
      no: string;
      /**
       * У найденной скриптом: отметить «возможно» (possible.py maybe).
       */
      mark?: string;
    };
  }[];
  /**
   * Сколько пар уже проверено — «нет».
   */
  ruled_out: number;
}
export interface Side {
  person: Id;
  born?: GDate;
  birth_place?: Id;
  died?: GDate;
  death_place?: Id;
  parents: Id[];
  /**
   * Сколько источников у карточки.
   */
  sources: number;
}
/**
 * Цифры по родам из ftree.toml и лента правок по дням. Считает tools/scripts/site_data/progress.py: лента — сравнение снимков дерева по последнему коммиту каждого дня, только из того, что посетитель и так видит на сайте. Люди — по cr_id; имя берётся из index.json.
 */
export interface ProgressFile {
  schema: "progress/1";
  total: {
    people: number;
    bios: number;
    /**
     * Людей хотя бы с одним фото.
     */
    pics: number;
    facts: number;
  };
  branches: Branch[];
  /**
   * Новые сверху.
   */
  days: Day[];
}
export interface Branch {
  /**
   * Имя рода, как в ftree.toml и в lineage карточек.
   */
  key: string;
  /**
   * cr_id деда или бабушки, с которых род начинается.
   */
  root: string | null;
  /**
   * Кровная родня (lineage).
   */
  people: number;
  /**
   * Супруги кровной родни (lineage_by_marriage), не кровные.
   */
  by_marriage: number;
  /**
   * На сколько поколений выше корня известны предки.
   */
  generations: number;
  /**
   * Сколько предков корня известно (без него самого).
   */
  ancestors: number;
  /**
   * cr_id предков на самом дальнем поколении (до 4).
   */
  deepest: string[];
  /**
   * Предок с самым ранним годом рождения.
   */
  oldest: {
    id: string;
    year: number;
  } | null;
  /**
   * Рождения и смерти корня и его предков (смерть живых не считаем): чем подтверждены — правила coverage.py.
   */
  docs: {
    events: number;
    /**
     * Документом: запись о событии или другая бумага.
     */
    record: number;
    /**
     * Только со слов семьи или по старому дереву.
     */
    family: number;
    /**
     * Ничем или только выводом и чужим деревом.
     */
    none: number;
  };
  bios: number;
  pics: number;
  /**
   * Сколько кровной родни прибавилось за 7 дней; null — истории нет.
   */
  week: number | null;
  /**
   * Кровной родни по дням с правками.
   */
  growth: {
    date: string;
    people: number;
  }[];
}
export interface Day {
  date: string;
  /**
   * Людей в дереве в конце дня.
   */
  people: number;
  /**
   * Карточек стало меньше (слияния) — только число.
   */
  removed: number;
  items: Change[];
}
export interface Change {
  id: string;
  /**
   * Новый человек в дереве.
   */
  new?: true;
  /**
   * Годы жизни: было, стало.
   *
   * @minItems 2
   * @maxItems 2
   */
  life?: [string, string];
  /**
   * Сколько фактов прибавилось.
   */
  facts?: number;
  bio?: "new" | "edit";
  /**
   * Сколько фото прибавилось.
   */
  pics?: number;
  /**
   * Привязаны родители (cr_id).
   */
  parents?: string[];
  /**
   * Привязаны супруги (cr_id).
   */
  spouses?: string[];
}
/**
 * Заметка, на которую есть ссылка из текстов сайта: расшифровка, полный текст находки, документ человека (2_transcripts/documents). Номер — первые 10 знаков md5 пути заметки, как у прежних страниц docs/<номер>.html (старые ссылки ведут сюда). Записи разговоров в семье — только описание (audio), без текста. goto — у старого адреса, у которого теперь своя страница (источник, биография человека).
 */
export interface DocFile {
  schema: "doc/1";
  id: DocId;
  /**
   * Старый адрес: открыть эту страницу вместо заметки.
   */
  goto?: {
    kind: "source" | "person";
    id: Id;
  };
  title?: string;
  /**
   * Где заметка лежит в проекте (2_transcripts/…) — подпись под названием.
   */
  path?: string;
  /**
   * Поля заметки, которые видны под названием.
   */
  meta?: {
    origin?: string;
    repository?: string;
    confidence?: string;
  };
  /**
   * Кто ссылается на заметку как на источник (sources карточки).
   */
  people?: Id[];
  media?: {
    url: string;
    kind: "photo";
    private: boolean;
  }[];
  /**
   * Файлы заметки (PDF и др.) — адрес от корня сайта.
   */
  files?: {
    name: string;
    url: string;
  }[];
  /**
   * Запись разговора в семье: на сайте только описание.
   */
  audio?: boolean;
  /**
   * Текст (Markdown, ссылки по номеру — как у источника).
   */
  md?: string;
}
/**
 * Что сборщику сайта нужно знать сверх data/: какие файлы отдавать только по паролю, когда и из каких стран вход открыт, куда выкладывать (цели из ftree.toml, [[site.target]]; нет целей — сайт только собирается). Пишет выгрузка (rodo site export) из карточек и ftree.toml [site]; сборщик (web/scripts/site.mjs) карточек не читает. На сайт этот файл не копируется: список закрытых файлов — только в проверке входа на сервере.
 */
export interface SiteFile {
  schema: "site/1";
  /**
   * Когда сделана выгрузка (UTC).
   */
  built?: string;
  /**
   * Адреса от корня сайта (/files/…, /media/…), которые без пароля не отдаются никогда.
   */
  private_files: string[];
  /**
   * Имя владельца сайта для пароля SITE_PASSWORD: [site] owner_login в ftree.toml; пусто — только USER_<ИМЯ>.
   */
  owner_login?: string;
  /**
   * Имя в окне входа (Basic realm): [site] realm в ftree.toml; пусто — «Family tree».
   */
  realm?: string;
  /**
   * До какого дня включительно вход без пароля из open_countries; '' — закрыто.
   */
  open_until: string;
  open_countries: string[];
  /**
   * Куда выкладывать: цели из ftree.toml дерева ([[site.target]]). Пусто — никуда.
   */
  deploy: {
    targets: {
      kind: "cloudflare-pages" | "folder" | "netlify" | "cloudflare-worker";
      /**
       * main — сам сайт (rodo site publish); mirror — пересылка на основной (rodo site mirror).
       */
      role: "main" | "mirror";
      /**
       * Имя на хостинге: проект Pages, сайт Netlify, воркер; у folder — путь к папке.
       */
      name: string;
      url?: string;
      /**
       * Выкладывать только по имени (rodo site publish|mirror <имя>).
       */
      manual?: true;
    }[];
  };
  /**
   * Сколько чего в выгрузке — для строки итога сборки.
   */
  counts?: {
    [k: string]: number;
  };
  /**
   * Имя дерева ([tree] name) — для файлов этого дерева на Mac (секрет зеркала ~/.config/ftree/<имя>/proxy_key).
   */
  tree?: string;
}
