import { DetailKlaim } from "@/components/DetailKlaim";

export default async function HalamanKlaim({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DetailKlaim id={id} />;
}