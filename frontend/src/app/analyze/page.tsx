import Link from "next/link";
import { ArrowRight, FileSearch, PlayCircle, ShieldCheck } from "lucide-react";

function ModeCard({
  eyebrow,
  title,
  description,
  href,
  action,
  icon,
}: {
  eyebrow: string;
  title: string;
  description: string;
  href: string;
  action: string;
  icon: React.ReactNode;
}) {
  return (
    <article className="card flex h-full flex-col p-6">
      <div className="flex items-center gap-2 text-accent-700">
        {icon}
        <p className="text-xs font-semibold uppercase tracking-wide">{eyebrow}</p>
      </div>
      <h2 className="mt-4 text-xl font-semibold tracking-tight text-slate-900">{title}</h2>
      <p className="mt-2 flex-1 text-sm leading-relaxed text-slate-600">{description}</p>
      <Link href={href} className="btn-primary mt-6 w-fit">
        {action}
        <ArrowRight className="h-4 w-4" aria-hidden />
      </Link>
    </article>
  );
}

export default function AnalyzePage() {
  return (
    <div className="mx-auto max-w-4xl space-y-7">
      <header className="max-w-3xl">
        <div className="flex items-center gap-2 text-accent-700">
          <ShieldCheck className="h-4 w-4" aria-hidden />
          <p className="text-xs font-semibold uppercase tracking-wide">Два независимых режима</p>
        </div>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
          Выберите режим работы
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">
          Демонстрация воспроизводит принятый результат Bayterek. Анализ нового проекта принимает
          реальные файлы и создаёт отдельное временное задание. Данные и результаты этих режимов
          не смешиваются.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <ModeCard
          eyebrow="Демонстрация"
          title="Демонстрация Bayterek"
          description="Воспроизводит ранее проверенный результат и показывает архитектуру P0–P4 и Meta."
          href="/analyze/demo"
          action="Открыть демонстрационный пакет"
          icon={<PlayCircle className="h-5 w-5" aria-hidden />}
        />
        <ModeCard
          eyebrow="Новый проект"
          title="Анализ нового проекта"
          description="Загружает документы и запускает фактическую обработку проекта."
          href="/analyze/live"
          action="Создать новый анализ"
          icon={<FileSearch className="h-5 w-5" aria-hidden />}
        />
      </div>

      <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-500">
        Результат DÁLEL — приоритет для экспертной проверки, а не вероятность нарушения и не
        юридическое заключение.
      </p>
    </div>
  );
}
