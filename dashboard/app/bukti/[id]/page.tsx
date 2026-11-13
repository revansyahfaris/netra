import { HalamanBukti } from "@/components/BuktiPublik";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <HalamanBukti id={id} />;
}