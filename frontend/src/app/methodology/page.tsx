import type { Metadata } from "next";
import { ChevronDown, Database, FileText, Gauge, Network, Scale, Sigma, UserCheck } from "lucide-react";

export const metadata: Metadata = {
  title: "Методология — Dalel",
};

function Block({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-6">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <div className="mt-3 space-y-2 text-sm leading-relaxed text-slate-600">{children}</div>
    </div>
  );
}

// Pure CSS/HTML architecture diagram (no image, no chart library): dataset in,
// four independent deterministic pillars, Meta aggregation, human decision out.
function ArchitectureDiagram() {
  const pillars = [
    { id: "P1", label: "Целостность" },
    { id: "P2", label: "Соответствие" },
    { id: "P3", label: "Согласованность" },
    { id: "P4", label: "Междокументная" },
  ];
  return (
    <div className="card p-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Архитектура потока данных
      </p>
      <div className="mt-5 flex flex-col items-center gap-2">
        <DiagramBox icon={Database} label="Куративный датасет v1" sub="провенанс до страницы/раздела" />
        <ChevronDown className="h-4 w-4 text-slate-300" aria-hidden />

        <div className="grid w-full max-w-2xl grid-cols-2 gap-3 sm:grid-cols-4">
          {pillars.map((p) => (
            <div key={p.id} className="rounded-lg border border-slate-200 bg-white p-3 text-center">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-accent-700">
                {p.id}
              </p>
              <p className="mt-0.5 text-xs text-slate-600">{p.label}</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-slate-400">независимо, детерминированно, каждый со своими доказательствами</p>
        <ChevronDown className="h-4 w-4 text-slate-300" aria-hidden />

        <DiagramBox icon={Gauge} label="Meta · интегральный балл" sub="прозрачная сумма вкладов P1–P4" accent />
        <ChevronDown className="h-4 w-4 text-slate-300" aria-hidden />

        <DiagramBox icon={UserCheck} label="Эксперт" sub="итоговое решение остаётся за человеком" />
      </div>
    </div>
  );
}

function DiagramBox({
  icon: Icon,
  label,
  sub,
  accent = false,
}: {
  icon: typeof Database;
  label: string;
  sub: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`flex w-full max-w-sm items-center gap-3 rounded-lg border p-3 ${
        accent ? "border-navy-800 bg-navy-900 text-white" : "border-slate-200 bg-slate-50"
      }`}
    >
      <span
        className={`flex h-9 w-9 flex-none items-center justify-center rounded-lg ${
          accent ? "bg-accent-600 text-white" : "bg-white text-accent-600"
        }`}
      >
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <p className={`text-sm font-medium ${accent ? "text-white" : "text-slate-800"}`}>{label}</p>
        <p className={`text-[11px] ${accent ? "text-slate-300" : "text-slate-500"}`}>{sub}</p>
      </div>
    </div>
  );
}

export default function MethodologyPage() {
  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Методология</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          Dalel — платформа доказательного анализа. Каждый вывод привязан к
          документу, странице и разделу, а решение остаётся за экспертом.
          Ниже — принципы и границы применимости.
        </p>
      </header>

      <ArchitectureDiagram />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Block title="Доказательная архитектура">
          <p>
            Анализ работает поверх принятого куративного датасета с полной
            провенанс-цепочкой: проект → документ → страница → раздел →
            таблица → ячейка. Ни одно наблюдение не появляется без ссылки на
            исходный фрагмент.
          </p>
        </Block>
        <Block title="Детерминированность">
          <p>
            Пиллары P1, P3 и P4 полностью детерминированы: одинаковый вход даёт
            байт-в-байт одинаковый результат, без обращения к внешним сервисам,
            эмбеддингам или OCR на этапе анализа.
          </p>
        </Block>
        <Block title="Человек в контуре">
          <p>
            Платформа формирует <span className="font-medium">кандидатов на проверку</span>,
            а не выводы. Формулировки намеренно осторожны: «потенциальное
            замечание», «требует экспертной проверки», «недостаточно
            доказательств».
          </p>
        </Block>
        <Block title="Что платформа НЕ делает">
          <p>
            Не подтверждает и не опровергает соответствие законодательству, не
            принимает решения о выдаче разрешений и не выносит административных
            выводов. Приоритетные оценки — это очередь на проверку, а не
            вероятности нарушений.
          </p>
        </Block>
      </div>

      <div className="space-y-4">
        <div className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-5">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-navy-900 text-white">
            <FileText className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              P1 · Целостность документов
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              Проверяет структурную полноту пакета и документов: ожидаемые
              разделы, пустые страницы, зависимость от OCR, повторы заголовков.
              Это наблюдения о структуре, а не юридические требования.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-4 rounded-xl border border-amber-200 bg-amber-50/50 p-5">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-amber-600 text-white">
            <Scale className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              P2 · Регуляторное соответствие (демонстрация)
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">
              Сопоставляет документы с требованиями на уровне отдельных норм.
              В текущем режиме используется{" "}
              <span className="font-semibold">синтетический демонстрационный корпус</span> —
              он не является официальным источником права. Метки отражают наличие
              лексических свидетельств, а не соответствие закону. Архитектура
              провайдеров совместима с подключением реальной языковой модели
              (в т.ч. AlemLLM) через конфигурацию, но по умолчанию LLM не
              вызывается.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-5">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-navy-900 text-white">
            <Sigma className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              P3 · Количественная согласованность
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              Ищет потенциально противоречивые числовые утверждения (значения,
              единицы, итоги таблиц). Сравнения с недостаточным контекстом
              сознательно исключаются из выводов, поэтому отсутствие замечаний не
              является подтверждением корректности документов.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-5">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-navy-900 text-white">
            <Network className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              P4 · Междокументная согласованность
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              Сопоставляет сведения о проекте, объектах, местоположении,
              деятельности и периодах между документами пакета и строит граф
              сущностей с сохранением провенанса. Конфликт поднимается только при
              явном несовместимом идентификаторе (например, разные БИН оператора);
              различия написания, кавычек и транслитерации считаются алиасами, а
              не противоречиями. Сопоставления с неустановленной идентичностью или
              недостаточным контекстом исключаются из выводов. Это не
              пространственный и не картографический анализ.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-4 rounded-xl border border-accent-100 bg-accent-50/40 p-5">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-accent-700 text-white">
            <Gauge className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Meta · Интегральная приоритетность проверки
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              Объединяет принятые свидетельства P1–P4 в воспроизводимый балл от
              0 до 100 и показывает точный вклад каждого фактора. Покрытие
              доказательств и уверенность рассчитываются отдельно; отсутствие
              замечаний P3/P4 не даёт «бонуса безопасности». Вклад P2 ограничен,
              поскольку нормативный корпус демонстрационный. Это порядок
              экспертной проверки, а не вероятность нарушения или
              административное решение.
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              Калиброванная вероятность и SHAP недоступны без достаточного числа
              реальных экспертных меток. В интерфейсе используются только точные
              вклады детерминированного алгоритма.
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/60 p-6">
        <h2 className="text-base font-semibold text-slate-700">Следующие этапы</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">
          Пространственный и картографический анализ (геопривязка объектов и зон
          воздействия) остаётся в разработке (P5/P6). Он не подменяется текущим
          междокументным или Meta-анализом.
        </p>
      </div>
    </div>
  );
}
