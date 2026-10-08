import { redirect } from "next/navigation";

export default function Home() {
  // Default entry point directs to hero demonstration bundle
  redirect("/workbench/default-bundle");
}
