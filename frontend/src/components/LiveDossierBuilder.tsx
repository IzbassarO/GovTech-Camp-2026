"use client";

import { useRef } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { Archive, FileText, Image as ImageIcon, Plus, X } from "lucide-react";

import type {
  LiveDossierSectionDefinition,
  LiveDossierSectionId,
} from "@/lib/types";
import { fileExtension, formatFileSize, materialsWord } from "@/lib/ui";

export interface PendingLiveFile {
  clientId: string;
  file: File;
  sectionId: LiveDossierSectionId;
}

const SECTION_HELP: Record<
  LiveDossierSectionId,
  { purpose: string; requirement: string; multiplicity: string; pillars: string[] }
> = {
  project_documents: {
    purpose: "Основные проектные материалы, расчёты, пояснительные записки и проектные решения.",
    requirement: "Ожидается для фактического анализа",
    multiplicity: "Один или несколько файлов",
    pillars: ["P1", "P2", "P3", "P4"],
  },
  official_supporting_documents: {
    purpose: "Решения уполномоченных органов и другие официальные подтверждающие материалы.",
    requirement: "Добавляется при наличии",
    multiplicity: "Ноль или несколько файлов",
    pillars: ["P1", "P2", "P4"],
  },
  hearing_protocol: {
    purpose: "Протокол общественных слушаний и приложения к нему.",
    requirement: "Добавляется при наличии",
    multiplicity: "Ноль или несколько файлов",
    pillars: ["P1", "P2", "P4"],
  },
  procedural_publication_evidence: {
    purpose: "Газетные публикации, уведомления и фото процедурных объявлений.",
    requirement: "Подтверждающий процедурный материал",
    multiplicity: "Ноль или несколько файлов",
    pillars: [],
  },
  visual_geographic_materials: {
    purpose: "Карты, схемы, фотографии площадки и другие визуальные материалы.",
    requirement: "Дополнительный материал",
    multiplicity: "Ноль или несколько файлов",
    pillars: [],
  },
  public_feedback_metadata: {
    purpose: "Количество обращений и вопросов из поддерживаемого структурированного источника.",
    requirement: "Необязательные структурированные данные",
    multiplicity: "Одна запись",
    pillars: [],
  },
};

function PendingFileIcon({ filename }: { filename: string }) {
  const extension = fileExtension(filename);
  if (extension === "zip" || extension === "rar") {
    return <Archive className="h-4 w-4 flex-none text-slate-400" aria-hidden />;
  }
  if (["jpg", "jpeg", "png"].includes(extension)) {
    return <ImageIcon className="h-4 w-4 flex-none text-slate-400" aria-hidden />;
  }
  return <FileText className="h-4 w-4 flex-none text-slate-400" aria-hidden />;
}

function PendingFileRow({
  item,
  sections,
  disabled,
  onMove,
  onRemove,
}: {
  item: PendingLiveFile;
  sections: LiveDossierSectionDefinition[];
  disabled: boolean;
  onMove: (sectionId: LiveDossierSectionId) => void;
  onRemove: () => void;
}) {
  const extension = fileExtension(item.file.name);
  const destinations = sections.filter(
    (section) => section.upload_enabled && section.accepted_formats.includes(extension),
  );
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <PendingFileIcon filename={item.file.name} />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="truncate text-sm font-medium text-slate-800">{item.file.name}</p>
        <p className="text-xs text-slate-500">
          {extension.toUpperCase()} · {formatFileSize(item.file.size)}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200">
            Ожидает защищённой загрузки
          </span>
          {destinations.length > 1 ? (
            <label className="flex items-center gap-1.5 text-[11px] text-slate-500">
              Раздел:
              <select
                value={item.sectionId}
                disabled={disabled}
                onChange={(event) => onMove(event.target.value as LiveDossierSectionId)}
                className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] text-slate-700 disabled:opacity-60"
              >
                {destinations.map((section) => (
                  <option key={section.section_id} value={section.section_id}>
                    {section.title_ru}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={onRemove}
        aria-label={`Удалить файл ${item.file.name}`}
        className="flex-none rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

export function LiveDossierSectionCard({
  definition,
  files,
  sections,
  disabled,
  onAddFiles,
  onMoveFile,
  onRemoveFile,
}: {
  definition: LiveDossierSectionDefinition;
  files: PendingLiveFile[];
  sections: LiveDossierSectionDefinition[];
  disabled: boolean;
  onAddFiles: (sectionId: LiveDossierSectionId, files: FileList) => void;
  onMoveFile: (fileId: string, sectionId: LiveDossierSectionId) => void;
  onRemoveFile: (fileId: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const help = SECTION_HELP[definition.section_id];

  const onDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    if (!disabled && definition.upload_enabled && event.dataTransfer.files.length > 0) {
      onAddFiles(definition.section_id, event.dataTransfer.files);
    }
  };
  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (!disabled && event.target.files && event.target.files.length > 0) {
      onAddFiles(definition.section_id, event.target.files);
    }
    event.target.value = "";
  };

  return (
    <section
      className="card overflow-hidden"
      aria-label={`Раздел ${definition.order}: ${definition.title_ru}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={onDrop}
    >
      <div className="space-y-2 border-b border-slate-100 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-navy-900 text-[11px] font-semibold text-white">
            {definition.order}
          </span>
          <h3 className="text-sm font-semibold text-slate-900">{definition.title_ru}</h3>
          {files.length > 0 ? (
            <span className="chip bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200">
              {files.length} {materialsWord(files.length)}
            </span>
          ) : null}
        </div>
        <p className="text-xs leading-relaxed text-slate-500">{help.purpose}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
          <span className="font-medium text-slate-500">{help.requirement}</span>
          {definition.accepted_formats.length > 0 ? (
            <span>{definition.accepted_formats.map((format) => format.toUpperCase()).join(", ")}</span>
          ) : null}
          <span>{help.multiplicity}</span>
          {help.pillars.length > 0 ? (
            <span className="font-medium text-accent-700">
              Возможный вход: {help.pillars.join(", ")}
            </span>
          ) : null}
        </div>
      </div>

      {files.length > 0 ? (
        <div className="divide-y divide-slate-100">
          {files.map((item) => (
            <PendingFileRow
              key={item.clientId}
              item={item}
              sections={sections}
              disabled={disabled}
              onMove={(sectionId) => onMoveFile(item.clientId, sectionId)}
              onRemove={() => onRemoveFile(item.clientId)}
            />
          ))}
        </div>
      ) : (
        <p className="px-4 py-3 text-xs text-slate-400">
          {definition.upload_enabled
            ? `Материалы не добавлены. ${help.requirement}.`
            : "Этот раздел заполняется только из поддерживаемого структурированного источника."}
        </p>
      )}

      {definition.upload_enabled ? (
        <div className="border-t border-dashed border-slate-200 p-3">
          <button
            type="button"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-accent-700 hover:bg-accent-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Добавить файл ({definition.accepted_formats.map((format) => format.toUpperCase()).join(", ")})
            — или перетащите сюда
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            disabled={disabled}
            accept={definition.accepted_formats.map((format) => `.${format}`).join(",")}
            className="sr-only"
            onChange={onInputChange}
          />
        </div>
      ) : null}
    </section>
  );
}
