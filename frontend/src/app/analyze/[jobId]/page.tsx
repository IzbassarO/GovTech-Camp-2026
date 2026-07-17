import { redirect } from "next/navigation";

/** Legacy ambiguous job URLs never guess whether a protected job is demo or live. */
export default function LegacyAnalyzeJobPage() {
  redirect("/analyze");
}
