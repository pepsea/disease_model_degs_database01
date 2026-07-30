/** 選択状態を URL クエリに同期させるフック。

解析結果をそのままリンクで共有できるようにするため、画面の選択は
すべて URL に持たせる（コンポーネントの内部 state に閉じ込めない）。
*/

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

export function useUrlState() {
  const [searchParams, setSearchParams] = useSearchParams();

  const get = useCallback(
    (key: string, fallback = ""): string => searchParams.get(key) ?? fallback,
    [searchParams],
  );

  const getList = useCallback(
    (key: string): string[] => {
      const raw = searchParams.get(key);
      return raw ? raw.split(",").filter(Boolean) : [];
    },
    [searchParams],
  );

  const getNumber = useCallback(
    (key: string, fallback: number): number => {
      const raw = searchParams.get(key);
      if (raw === null) return fallback;
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : fallback;
    },
    [searchParams],
  );

  const getBool = useCallback(
    (key: string, fallback = false): boolean => {
      const raw = searchParams.get(key);
      return raw === null ? fallback : raw === "1" || raw === "true";
    },
    [searchParams],
  );

  /** 複数キーをまとめて更新する。空文字/空配列/false はキーを削除する。 */
  const patch = useCallback(
    (updates: Record<string, string | string[] | number | boolean | null | undefined>) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(updates)) {
            const empty =
              value === null ||
              value === undefined ||
              value === "" ||
              value === false ||
              (Array.isArray(value) && value.length === 0);
            if (empty) next.delete(key);
            else if (Array.isArray(value)) next.set(key, value.join(","));
            else if (typeof value === "boolean") next.set(key, "1");
            else next.set(key, String(value));
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return useMemo(
    () => ({ get, getList, getNumber, getBool, patch, searchParams }),
    [get, getList, getNumber, getBool, patch, searchParams],
  );
}
