"""Подписи эпох («Государства по годам») на языках сайта. Общие для HTML-страниц и для JSON.

Перевод — по кускам: каждый известный кусок подписи заменяется своим переводом (сначала длинные). Если после замены
осталась хоть одна русская буква — подпись на этом языке не показываем переводом, а оставляем русской целиком:
лучше русский текст, чем смесь. Новая подпись эпохи в карточке места — строка сюда (CLAUDE.md, «Ошибки», «Новая страна без эпох»).
"""
from .names import CYR

ERA_TR = {  # по-русски: (по-польски, по-испански, по-английски)
    "Российская империя": ("Imperium Rosyjskie", "Imperio ruso", "Russian Empire"),
    "Пруссия": ("Prusy", "Prusia", "Prussia"),
    "II Речь Посполитая": ("II Rzeczpospolita", "Segunda República de Polonia", "Second Polish Republic"),
    "польско-советская война": ("wojna polsko-bolszewicka", "guerra polaco-soviética", "Polish–Soviet War"),
    "немецкая оккупация": ("okupacja niemiecka", "ocupación alemana", "German occupation"),
    "с 1922 в составе СССР": ("od 1922 w składzie ZSRR", "desde 1922 parte de la URSS", "part of the USSR from 1922"),
    "Польша": ("Polska", "Polonia", "Poland"), "СССР": ("ZSRR", "URSS", "USSR"),
    "БССР": ("BSRR", "RSS de Bielorrusia", "Byelorussian SSR"), "Беларусь": ("Białoruś", "Bielorrusia", "Belarus"),
    # Аргентина и Парагвай — места аргентинской ветви (карточки мест, «Государства по годам»)
    "Аргентинская Республика, выборная власть (радикалы: Иригойен, Альвеар)": (
        "Republika Argentyńska, władza wybieralna (radykałowie: Yrigoyen, Alvear)",
        "República Argentina, gobiernos electos (radicales: Yrigoyen, Alvear)",
        "Argentine Republic, elected governments (Radicals: Yrigoyen, Alvear)"),
    "«позорное десятилетие»: после военного переворота 6.09.1930 правят консерваторы, выборы с подлогом": (
        "„haniebna dekada”: po zamachu wojskowym 6.09.1930 rządzą konserwatyści, wybory fałszowane",
        "la «Década Infame»: tras el golpe militar del 6.09.1930 gobiernan los conservadores con fraude electoral",
        "the “Infamous Decade”: after the military coup of 6 Sep 1930, conservatives rule through electoral fraud"),
    "военное правительство после революции 4.06.1943": (
        "rząd wojskowy po rewolucji 4.06.1943", "gobierno militar tras la Revolución del 43 (4.06.1943)",
        "military government after the Revolution of 4 June 1943"),
    "военное правительство после революции 4.06.1943; поднимается полковник Перон": (
        "rząd wojskowy po rewolucji 4.06.1943; wzrasta pułkownik Perón",
        "gobierno militar tras la Revolución del 43 (4.06.1943); asciende el coronel Perón",
        "military government after the Revolution of 4 June 1943; Colonel Perón rises"),
    "президент Перон: стройки, профсоюзы, права рабочих": (
        "prezydent Perón: budowy, związki zawodowe, prawa robotników",
        "presidencia de Perón: obra pública, sindicatos, derechos de los trabajadores",
        "President Perón: construction, trade unions, workers’ rights"),
    "военная «Освободительная революция»: Перона свергли в сентябре 1955": (
        "wojskowa „Rewolucja Wyzwoleńcza”: Perón obalony we wrześniu 1955",
        "la «Revolución Libertadora» militar: Perón derrocado en septiembre de 1955",
        "the military “Liberating Revolution”: Perón overthrown in September 1955"),
    "гражданские президенты под надзором армии (Фрондиси, Гидо, Ильиа); перонисты под запретом": (
        "cywilni prezydenci pod nadzorem armii (Frondizi, Guido, Illia); peroniści zakazani",
        "presidentes civiles bajo tutela militar (Frondizi, Guido, Illia); peronismo proscrito",
        "civilian presidents under army oversight (Frondizi, Guido, Illia); Peronism banned"),
    "военная диктатура «Аргентинская революция» (Онганиа, Левингстон, Лануссе)": (
        "dyktatura wojskowa „Rewolucja Argentyńska” (Onganía, Levingston, Lanusse)",
        "dictadura militar de la «Revolución Argentina» (Onganía, Levingston, Lanusse)",
        "military dictatorship of the “Argentine Revolution” (Onganía, Levingston, Lanusse)"),
    "снова перонисты: Перон (1973–1974), после его смерти — Исабель Перон": (
        "znów peroniści: Perón (1973–1974), po jego śmierci — Isabel Perón",
        "vuelve el peronismo: Perón (1973–1974) y, tras su muerte, Isabel Perón",
        "Peronists again: Perón (1973–1974), then after his death Isabel Perón"),
    "военная диктатура «Процесс национальной реорганизации»: «грязная война», до 30 тыс. «исчезнувших»": (
        "dyktatura wojskowa „Proces Reorganizacji Narodowej”: „brudna wojna”, do 30 tys. „zaginionych”",
        "dictadura militar del «Proceso de Reorganización Nacional»: «guerra sucia», hasta 30 000 desaparecidos",
        "military dictatorship of the “National Reorganization Process”: the “Dirty War”, up to 30,000 disappeared"),
    "Мальвинская (Фолклендская) война с Великобританией": (
        "wojna o Malwiny (Falklandy) z Wielką Brytanią", "Guerra de Malvinas con Gran Bretaña",
        "Falklands (Malvinas) War with Britain"),
    "демократия (с 10.12.1983, президент Альфонсин)": (
        "demokracja (od 10.12.1983, prezydent Alfonsín)", "democracia (desde el 10.12.1983, presidente Alfonsín)",
        "democracy (from 10 Dec 1983, President Alfonsín)"),
    "Республика Парагвай, правление либералов": (
        "Republika Paragwaju, rządy liberałów", "República del Paraguay, gobiernos liberales",
        "Republic of Paraguay, Liberal governments"),
    "война Чако с Боливией (до 12.06.1935)": (
        "wojna o Chaco z Boliwią (do 12.06.1935)", "Guerra del Chaco con Bolivia (hasta el 12.06.1935)",
        "Chaco War with Bolivia (until 12 June 1935)"),
    "«Февральская революция»: военный переворот 17.02.1936, полковник Франко": (
        "„Rewolucja Lutowa”: zamach wojskowy 17.02.1936, pułkownik Franco",
        "la «Revolución de Febrero»: golpe militar del 17.02.1936, coronel Franco",
        "the “February Revolution”: military coup of 17 Feb 1936, Colonel Franco"),
    "снова либералы: Паива, маршал Эстигаррибия (погиб 7.09.1940)": (
        "znów liberałowie: Paiva, marszałek Estigarribia (zginął 7.09.1940)",
        "vuelven los liberales: Paiva y el mariscal Estigarribia (muerto el 7.09.1940)",
        "Liberals again: Paiva, Marshal Estigarribia (killed 7 Sep 1940)"),
    "диктатура генерала Мориниго": ("dyktatura generała Morínigo", "dictadura del general Morínigo",
                                    "dictatorship of General Morínigo"),
    "гражданская война": ("wojna domowa", "guerra civil", "civil war"),
    "смута: партия Колорадо, частая смена президентов": (
        "zamęt: partia Colorado, częste zmiany prezydentów", "inestabilidad: Partido Colorado, presidentes que se suceden",
        "turmoil: Colorado Party, frequent changes of president"),
    "диктатура генерала Стресснера": ("dyktatura generała Stroessnera", "dictadura del general Stroessner",
                                      "dictatorship of General Stroessner"),
    "демократия": ("demokracja", "democracia", "democracy"),
    "Австро-Венгрия": ("Austro-Węgry", "Austria-Hungría", "Austria-Hungary"),
    "под управлением Италии после Первой мировой": ("pod zarządem Włoch po I wojnie światowej",
                                                    "bajo administración italiana tras la Primera Guerra Mundial",
                                                    "under Italian administration after the First World War"),
    "Королевство Италия": ("Królestwo Włoch", "Reino de Italia", "Kingdom of Italy"),
    "диктатура Муссолини": ("dyktatura Mussoliniego", "dictadura de Mussolini", "Mussolini's dictatorship"),
    "югославская, затем англо-американская военная администрация": (
        "administracja wojskowa jugosłowiańska, potem angielsko-amerykańska",
        "administración militar yugoslava, luego angloamericana", "Yugoslav, then Anglo-American military administration"),
    "Свободная территория Триест": ("Wolne Terytorium Triestu", "Territorio Libre de Trieste", "Free Territory of Trieste"),
    "Италия": ("Włochy", "Italia", "Italy"),
    "Королевство Нидерландов": ("Królestwo Niderlandów", "Reino de los Países Bajos", "Kingdom of the Netherlands"),
    # страны и города без своих эпох до 28.09.2026: Россия, Украина, Польша, Германия, США, Бразилия, Вильнюс, Рига, Казахстан
    "Советская Россия": ("Rosja Radziecka", "Rusia Soviética", "Soviet Russia"), "РСФСР": ("RFSRR", "RSFS de Rusia", "RSFSR"),
    "Россия": ("Rosja", "Rusia", "Russia"),
    "Украинская народная республика": ("Ukraińska Republika Ludowa", "República Popular Ucraniana", "Ukrainian People's Republic"),
    "Украинская держава": ("Państwo Ukraińskie", "Estado Ucraniano", "Ukrainian State"),
    "УССР": ("USRR", "RSS de Ucrania", "Ukrainian SSR"), "Украина": ("Ukraina", "Ucrania", "Ukraine"),
    "оккупация (немецкая, в Одессе — румынская)": ("okupacja (niemiecka, w Odessie — rumuńska)",
                                                  "ocupación (alemana; en Odesa, rumana)", "occupation (German; in Odesa, Romanian)"),
    "разделы Польши (Россия, Пруссия, Австрия)": ("rozbiory Polski (Rosja, Prusy, Austria)",
                                                 "particiones de Polonia (Rusia, Prusia, Austria)",
                                                 "partitions of Poland (Russia, Prussia, Austria)"),
    "ПНР": ("PRL", "República Popular de Polonia", "Polish People's Republic"),
    "III Речь Посполитая": ("III Rzeczpospolita", "Tercera República de Polonia", "Third Polish Republic"),
    "Варшавское герцогство": ("Księstwo Warszawskie", "Ducado de Varsovia", "Duchy of Warsaw"),
    "Царство Польское": ("Królestwo Polskie", "Reino de Polonia", "Kingdom of Poland"),
    "Германская империя": ("Cesarstwo Niemieckie", "Imperio alemán", "German Empire"),
    "Веймарская республика": ("Republika Weimarska", "República de Weimar", "Weimar Republic"),
    "нацистская Германия": ("nazistowskie Niemcy", "Alemania nazi", "Nazi Germany"),
    "оккупация союзниками": ("okupacja aliancka", "ocupación aliada", "Allied occupation"),
    "ФРГ и ГДР": ("RFN i NRD", "RFA y RDA", "West and East Germany"), "Германия": ("Niemcy", "Alemania", "Germany"),
    "США": ("USA", "EE. UU.", "USA"),
    "Грузинская Демократическая Республика": ("Demokratyczna Republika Gruzji", "República Democrática de Georgia",
                                              "Democratic Republic of Georgia"),
    "Грузинская ССР": ("Gruzińska SRR", "RSS de Georgia", "Georgian SSR"), "Грузия": ("Gruzja", "Georgia", "Georgia"),
    "Бразильская империя": ("Cesarstwo Brazylii", "Imperio de Brasil", "Empire of Brazil"),
    "Бразилия (республика)": ("Brazylia (republika)", "Brasil (república)", "Brazil (republic)"),
    "Литва, Советы и Польша по очереди": ("na przemian Litwa, bolszewicy i Polska", "Lituania, los soviéticos y Polonia, por turnos",
                                         "Lithuania, the Soviets and Poland in turn"),
    "Срединная Литва": ("Litwa Środkowa", "Lituania Central", "Central Lithuania"),
    "Литовская ССР": ("Litewska SRR", "RSS de Lituania", "Lithuanian SSR"), "Литва": ("Litwa", "Lituania", "Lithuania"),
    "Эстонская Республика": ("Republika Estońska", "República de Estonia", "Republic of Estonia"),
    "Эстонская ССР": ("Estońska SRR", "RSS de Estonia", "Estonian SSR"), "Эстония": ("Estonia", "Estonia", "Estonia"),
    "Финляндия (Петсамо)": ("Finlandia (Petsamo)", "Finlandia (Petsamo)", "Finland (Petsamo)"),
    "Латвийская ССР": ("Łotewska SRR", "RSS de Letonia", "Latvian SSR"), "Латвия": ("Łotwa", "Letonia", "Latvia"),
    "Казахская АССР": ("Kazachska ASRR", "RASS de Kazajistán", "Kazakh ASSR"),
    "Казахская ССР": ("Kazachska SRR", "RSS de Kazajistán", "Kazakh SSR"), "Казахстан": ("Kazachstan", "Kazajistán", "Kazakhstan"),
}


def translate(ru):
    """«Польша (II Речь Посполитая)» → {ru, pl, es, en}."""
    out = {"ru": ru}
    for i, lang in enumerate(("pl", "es", "en")):
        t = ru
        for k, v in sorted(ERA_TR.items(), key=lambda x: -len(x[0])):
            t = t.replace(k, v[i])
        out[lang] = t if not CYR.search(t) else ru
    return out
