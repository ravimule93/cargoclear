"use client";

import { useCallback, useState } from "react";
import { NO_DECLARED_TYPE } from "@/lib/documentTypes";

/**
 * "What is the NEXT file?" (the type menu beside an upload control). The answer is optional and labels ONE file:
 * - while a type is chosen the file dialog allows a single file (`allowsSeveralFiles` is false) and a multi-file drop is refused;
 * - `take()` hands the choice to the upload and clears it, so a stale choice never labels an unrelated file later.
 */
export function useDeclaredType() {
  const [declaredType, setDeclaredType] = useState<string>(NO_DECLARED_TYPE);
  const stated = declaredType !== NO_DECLARED_TYPE;

  /** The type to send with the next upload, or null when none was stated; the choice is forgotten. */
  const take = useCallback((): string | null => {
    setDeclaredType(NO_DECLARED_TYPE);
    return declaredType === NO_DECLARED_TYPE ? null : declaredType;
  }, [declaredType]);

  return { declaredType, setDeclaredType, stated, allowsSeveralFiles: !stated, take };
}
