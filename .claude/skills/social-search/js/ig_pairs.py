"""Текст окна «Подписчики/Подписки» Instagram (вывод ig_list.js) → строки «аккаунт<TAB>имя» для social_targets.py match.
    python3 ig_pairs.py вывод.txt > список.tsv"""
import re, sys
L = [l.strip() for l in open(sys.argv[1]) if l.strip() and l.strip() not in ("Follow", "Following", "Remove", "·", "Message", "Requested")]
i = 0
while i < len(L):
    if re.fullmatch(r"[a-z0-9._]+", L[i]):
        n = L[i + 1] if i + 1 < len(L) and not re.fullmatch(r"[a-z0-9._]+", L[i + 1]) else ""
        print(f"{L[i]}\t{n}"); i += 2 if n else 1
    else:
        i += 1
