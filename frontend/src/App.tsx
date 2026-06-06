import { Link, NavLink, Route, Routes } from "react-router-dom";

import Connections from "./pages/Connections";
import DagList from "./pages/DagList";
import DagDetail from "./pages/DagDetail";
import DagEdit from "./pages/DagEdit";
import DagNew from "./pages/DagNew";
import RunDetail from "./pages/RunDetail";
import Variables from "./pages/Variables";

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? "text-neutral-100" : "text-neutral-500 hover:text-neutral-300";

export default function App() {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-200">
      <header className="border-b border-neutral-800 bg-neutral-900/60 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center gap-6">
          <Link to="/" className="font-mono text-lg font-semibold tracking-tight text-emerald-400">
            airflowclone
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <NavLink to="/" end className={navClass}>
              dags
            </NavLink>
            <NavLink to="/variables" className={navClass}>
              variables
            </NavLink>
            <NavLink to="/connections" className={navClass}>
              connections
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<DagList />} />
          <Route path="/dags/new" element={<DagNew />} />
          <Route path="/dags/:dagId/edit" element={<DagEdit />} />
          <Route path="/dags/:dagId" element={<DagDetail />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/variables" element={<Variables />} />
          <Route path="/connections" element={<Connections />} />
        </Routes>
      </main>
    </div>
  );
}
