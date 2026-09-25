#!/usr/bin/env bash
# Ban string interpolation in raw SQL. Prisma has no string-building API to
# misuse, so query_raw/execute_raw are the only places injection can enter.
# The discipline is enforced here, not remembered.
set -euo pipefail

hits=$(grep -rnE '(query_raw|execute_raw)\s*\(\s*(f"|f'"'"'|.*%\s|.*"\s*\+)' \
        --include='*.py' api/app api/tests prisma 2>/dev/null || true)

if [ -n "$hits" ]; then
  echo "Raw SQL built by interpolation. Use positional parameters (\$1, \$2):"
  echo "$hits"
  exit 1
fi
echo "raw-SQL guard: clean"
