import { useCallSession } from "./hooks/useCallSession";
import ProductLandingExperience from "./components/ProductLandingExperience";

export default function App() {
  const session = useCallSession();
  return <ProductLandingExperience session={session} />;
}
