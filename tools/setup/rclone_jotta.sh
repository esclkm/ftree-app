#!/bin/sh
# Помощник для одного из хранилищ медиа — Jottacloud (другие — S3/R2, Google Drive… — заводятся `rclone config`).
# Один раз на Mac. Запуск: sh tools/setup/rclone_jotta.sh <имя>   (имя remote — любое, например «cloud» — пример)
#
# Что делает. rclone — программа, которая кладёт файлы в облако. Ей нужен свой ключ входа в Jottacloud
# (приложение Jottacloud на Mac ей не помогает). Скрипт:
#   1. открывает страницу Jottacloud, где выдают одноразовый токен, и просит вставить его — remote `<имя>`;
#   2. сам придумывает два пароля шифрования и кладёт их в Связку ключей (rclone-crypt-password, rclone-crypt-salt);
#      поверх `<имя>:ftree` заводит шифрованный remote `<имя>-crypt` — имена и содержимое файлов зашифрованы;
#   3. запирает файл настроек rclone третьим паролем (Связка ключей, rclone-config) и кладёт копию файла в облако;
#   4. просит сохранить два пароля шифрования ещё и в приложении «Пароли»: Связка ключей из командной строки живёт
#      только на этом Mac, а «Пароли» — в iCloud. Без этих двух паролей облачная копия — мусор (план, раздел 4.2);
#   5. печатает, что вписать в ftree.toml дерева ([storage.media], [storage.private]) — сам не вписывает.
# Пароли видны только в этом окне терминала; в файлы проекта они не попадают.
set -e
NAME=$1
case "$NAME" in
  ""|*[!A-Za-z0-9_-]*) echo "sh tools/setup/rclone_jotta.sh <имя>  — имя remote латиницей (пример: cloud)"; exit 2 ;;
esac
CRYPT="$NAME-crypt"
command -v rclone >/dev/null || { echo "нет rclone: brew install rclone"; exit 1; }
KC="security find-generic-password -s rclone-config -w"
if security find-generic-password -s rclone-config >/dev/null 2>&1; then export RCLONE_PASSWORD_COMMAND="$KC"; fi
if rclone listremotes 2>/dev/null | grep -qx "$CRYPT:"; then
  echo "$CRYPT уже есть — ничего не делаю (новые пароли сделали бы облачную копию нечитаемой)."; exit 0
fi

if ! rclone listremotes 2>/dev/null | grep -qx "$NAME:"; then
  echo
  echo "Шаг 1. Сейчас откроется jottacloud.com → Settings → Security."
  echo "        Там: «Personal login token» → Generate → скопировать (Cmd+C)."
  echo "        Потом сюда: вставить (Cmd+V) и Enter. На вопросы ниже — просто Enter."
  printf "Enter — открыть страницу… "; read _
  open "https://www.jottacloud.com/web/secure"
  rclone config create "$NAME" jottacloud config_type=standard
fi
echo; echo "Проверка: место в Jottacloud"; rclone about "$NAME:"

# Новый Mac: пароли шифрования НЕ придумывать заново — со старыми не прочитать то, что уже в облаке. Сначала вписать
# оба из приложения «Пароли» в Связку ключей (INSTALL.md, шаг «Облако»), тогда скрипт возьмёт их.
if P1=$(security find-generic-password -s rclone-crypt-password -w 2>/dev/null) &&
   P2=$(security find-generic-password -s rclone-crypt-salt -w 2>/dev/null); then
  RESTORED=1; echo; echo "Шаг 2. Пароли шифрования — беру из Связки ключей (уже были)"
else
  echo; echo "Шаг 2. Пароли шифрования — придумываю и кладу в Связку ключей"
  P1=$(openssl rand -base64 33 | tr -d '\n'); P2=$(openssl rand -base64 33 | tr -d '\n')
  security add-generic-password -U -a "$USER" -s rclone-crypt-password -w "$P1"
  security add-generic-password -U -a "$USER" -s rclone-crypt-salt -w "$P2"
fi
rclone config create "$CRYPT" crypt remote="$NAME:ftree" filename_encryption=standard \
  directory_name_encryption=true password="$P1" password2="$P2" >/dev/null
echo "$CRYPT готов"

if ! security find-generic-password -s rclone-config >/dev/null 2>&1; then
  echo; echo "Шаг 3. Запираю файл настроек rclone паролем из Связки ключей"
  security add-generic-password -U -a "$USER" -s rclone-config -w "$(openssl rand -base64 33 | tr -d '\n')"
  RCLONE_PASSWORD_CHANGE=1 RCLONE_PASSWORD_COMMAND="$KC" rclone config encryption set
fi
export RCLONE_PASSWORD_COMMAND="$KC"
rclone copyto "$(rclone config file | tail -1)" "$NAME:rclone-conf-backup/rclone.conf"
echo "копия файла настроек (он заперт паролем) — в $NAME:rclone-conf-backup/"

if [ -z "$RESTORED" ]; then
  echo; echo "Шаг 4. Сохранить два пароля в приложении «Пароли» (это переживёт потерю Mac)."
  echo "        Откройте «Пароли» → «+» → Название: rclone $CRYPT → поле «Пароль» — вставить (Cmd+V)."
  echo "        В «Заметки» той же записи — второй пароль (salt)."
  printf "Enter — скопировать первый пароль в буфер… "; read _
  printf %s "$P1" | pbcopy; echo "скопирован — вставьте в поле «Пароль»"
  printf "Enter — скопировать второй пароль (salt)… "; read _
  printf %s "$P2" | pbcopy; echo "скопирован — вставьте в «Заметки»"
  printf "Enter — очистить буфер… "; read _
  printf '' | pbcopy
fi
cat <<TOML

Готово. В ftree.toml дерева вписать (папку для фото назвать по-своему):
  [storage]
  push_after_commit = true
  [storage.media]
  kind = "rclone"
  address = "$NAME:Фото/"
  [storage.private]
  kind = "rclone"
  address = "$CRYPT:"
  encrypted = true
Потом rodo setup --check и напишите Claude «готово».
TOML
