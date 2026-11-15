"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../client/task-client";
import {
  actOnRobustnessStudy,
  createRobustnessStudy,
  exportRobustnessStudy,
  listRobustnessStudies,
  readRobustnessStudy,
  type CreateStudyInput,
} from "../../client/robustness";
import type { RobustnessStudy, StudyDirectoryEntry } from "../../contracts/robustness-study";
import { readStudyHandoff, studyRunning } from "./robustness-draft";
import type { ElectrodeDesign } from "../../lib/design-decision";

/** Mutation outcomes are recovered with reads. Navigation and polling never submit cases. */
export function useRobustnessController() {
  const [directory, setDirectory] = useState<StudyDirectoryEntry[]>([]),
    [study, setStudy] = useState<RobustnessStudy | null>(null);
  const [handoff, setHandoff] = useState<ElectrodeDesign | null>(null),
    [notice, setNotice] = useState(""),
    [error, setError] = useState("");
  const [busy, setBusy] = useState(false),
    [uncertain, setUncertain] = useState(false);
  const [connection, setConnection] = useState<"connected" | "reconnecting" | "blocked">(
    "connected",
  );
  const [refresh, setRefresh] = useState(0),
    [loading, setLoading] = useState(true);
  const mounted = useRef(true),
    selectedId = useRef<string | null>(null),
    selection = useRef(0);
  const reading = useRef<AbortController | null>(null),
    writing = useRef<AbortController | null>(null),
    listing = useRef<AbortController | null>(null);
  const uncertainRef = useRef(false),
    latestRevision = useRef(new Map<string, number>());
  const update = useCallback((value: RobustnessStudy) => {
    const revision = latestRevision.current.get(value.id) ?? 0;
    if (value.revision < revision) return;
    latestRevision.current.set(value.id, value.revision);
    setStudy(value);
    setConnection("connected");
    setDirectory((rows) => [
      {
        id: value.id,
        title: value.title,
        protocol: value.protocol,
        status: value.status,
        created_at: value.created_at,
        updated_at: value.updated_at,
        case_count: value.cases.length,
        completed_cases: value.aggregation.completed_cases,
      },
      ...rows.filter((row) => row.id !== value.id),
    ]);
  }, []);
  const refreshDirectory = useCallback(async () => {
    listing.current?.abort();
    const controller = new AbortController();
    listing.current = controller;
    try {
      const value = await listRobustnessStudies(controller.signal);
      if (!controller.signal.aborted && mounted.current) setDirectory(value.studies);
    } catch (caught) {
      if (!controller.signal.aborted && mounted.current)
        setError(caught instanceof Error ? caught.message : "研究目录无法读取");
    }
  }, []);
  const open = useCallback(
    async (id: string) => {
      reading.current?.abort();
      writing.current?.abort();
      writing.current = null;
      setBusy(false);
      const controller = new AbortController();
      reading.current = controller;
      selectedId.current = id;
      const version = ++selection.current;
      setLoading(true);
      setError("");
      setStudy(null);
      try {
        const { study: value } = await readRobustnessStudy(id, controller.signal);
        if (!controller.signal.aborted && mounted.current && selection.current === version) {
          update(value);
          uncertainRef.current = false;
          setUncertain(false);
          window.history.replaceState(null, "", "/robustness?study=" + id);
        }
      } catch (caught) {
        if (!controller.signal.aborted && mounted.current && selection.current === version)
          setError(caught instanceof Error ? caught.message : "研究无法读取");
      } finally {
        if (mounted.current && selection.current === version) setLoading(false);
      }
    },
    [update],
  );
  const disposeOperations = useCallback(() => { mounted.current = false; selection.current++; listing.current?.abort(); reading.current?.abort(); writing.current?.abort(); }, []);
  useEffect(() => {
    mounted.current = true;
    void Promise.resolve().then(() => {
      if (!mounted.current) return;
      const q = new URLSearchParams(window.location.search);
      if (q.get('draft') === '1') {
        try { const draft = readStudyHandoff(window.sessionStorage); setHandoff(draft); setNotice(draft ? '已恢复原始坐标与名称草稿；尚未创建或启动研究。' : '没有可恢复的坐标草稿，请重新导入。'); }
        catch (caught) { setError(caught instanceof Error ? caught.message : '研究坐标草稿无法恢复'); }
      }
      void refreshDirectory();
      const restoredId = q.get('study'); if (restoredId) void open(restoredId); else setLoading(false);
    });
    return disposeOperations;
  }, [open, refreshDirectory, disposeOperations]);
  const id = study?.id,
    status = study?.status;
  useEffect(() => {
    if (!id || !studyRunning(status)) return;
    const controller = new AbortController();
    let failures = 0,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await readRobustnessStudy(id, controller.signal);
        if (controller.signal.aborted || selectedId.current !== id) return;
        failures = 0;
        update(value.study);
        setError("");
        if (studyRunning(value.study.status)) timer = setTimeout(poll, 1000);
      } catch (caught) {
        if (controller.signal.aborted || selectedId.current !== id) return;
        failures++;
        setConnection(failures >= 3 ? "blocked" : "reconnecting");
        setError(caught instanceof Error ? caught.message : "研究连接中断");
        if (failures < 3) timer = setTimeout(poll, 1000 * 2 ** failures);
      }
    };
    timer = setTimeout(poll, 1000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, status, refresh, update]);
  const perform = async (work: (signal: AbortSignal) => Promise<RobustnessStudy>) => {
    if (writing.current || uncertainRef.current) return;
    const controller = new AbortController(),
      version = selection.current;
    writing.current = controller;
    listing.current?.abort();
    setBusy(true);
    setError("");
    try {
      const value = await work(controller.signal);
      if (mounted.current && !controller.signal.aborted && selection.current === version) {
        selectedId.current = value.id;
        update(value);
        window.history.replaceState(null, "", "/robustness?study=" + value.id);
      }
    } catch (caught) {
      if (mounted.current && !controller.signal.aborted && selection.current === version) {
        const unknown =
          !(caught instanceof ApiError) ||
          caught.status === 0 ||
          caught.status === 408 ||
          caught.status >= 500;
        uncertainRef.current = unknown;
        setUncertain(unknown);
        setError(
          unknown
            ? "操作返回前连接中断。请重新读取研究或刷新目录，核对已保存状态后再操作。"
            : caught.message,
        );
      }
    } finally {
      if (writing.current === controller) {
        writing.current = null;
        if (mounted.current) setBusy(false);
      }
    }
  };
  const create = (input: CreateStudyInput) =>
    perform(async (signal) => (await createRobustnessStudy(input, signal)).study);
  const act = (action: "start" | "resume" | "cancel") => {
    if (study)
      return perform(
        async (signal) => (await actOnRobustnessStudy(study.id, action, signal)).study,
      );
  };
  const reload = () => {
    if (selectedId.current) {
      setRefresh((value) => value + 1);
      void open(selectedId.current);
    } else void refreshDirectory();
  };
  const newDraft = () => {
    reading.current?.abort();
    writing.current?.abort();
    writing.current = null;
    selectedId.current = null;
    selection.current++;
    setStudy(null);
    setError("");
    setLoading(false);
    setBusy(false);
    uncertainRef.current = false;
    setUncertain(false);
    window.history.replaceState(null, "", "/robustness");
  };
  return {
    directory,
    study,
    handoff,
    notice,
    error,
    busy,
    uncertain,
    loading,
    connection,
    open,
    create,
    act,
    reload,
    refreshDirectory,
    newDraft,
    exportText: (signal?: AbortSignal) =>
      study ? exportRobustnessStudy(study.id, signal) : Promise.reject(new Error("请先打开研究")),
  };
}
