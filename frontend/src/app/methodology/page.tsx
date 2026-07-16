import type { Metadata } from "next";
import { FileText, Network, Scale, Sigma } from "lucide-react";

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
      </div>

      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/60 p-6">
        <h2 className="text-base font-semibold text-slate-700">Следующие этапы</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">
          Пространственный и картографический анализ (геопривязка объектов и зон
          воздействия) и интегральная оценка риска на основе всех пилларов — в
          разработке (P5/P6, META). Сейчас сводная калиброванная оценка риска не
          рассчитывается и не отображается.
        </p>
      </div>
    </div>
  );
}
