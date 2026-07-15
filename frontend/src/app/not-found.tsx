import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-4 py-20 text-center">
      <p className="text-5xl font-semibold text-slate-300">404</p>
      <p className="text-sm text-slate-600">Страница не найдена.</p>
      <Link href="/" className="btn-primary">
        На главную
      </Link>
    </div>
  );
}
