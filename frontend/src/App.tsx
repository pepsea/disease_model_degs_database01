import { NavLink, Route, Routes } from "react-router-dom";
import { Analysis } from "./pages/Analysis";
import { Browse } from "./pages/Browse";
import { Compare } from "./pages/Compare";
import { DatasetDetail } from "./pages/DatasetDetail";
import { Docs } from "./pages/Docs";
import { GeneView } from "./pages/GeneView";

const NAV = [
  { to: "/", label: "データセット" },
  { to: "/genes", label: "遺伝子" },
  { to: "/compare", label: "比較" },
  { to: "/analysis", label: "解析" },
  { to: "/docs", label: "データ登録" },
];

export default function App() {
  return (
    <>
      <header className="appbar">
        <div className="appbar__brand">疾患モデル遺伝子発現データベース</div>
        <nav className="appbar__nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Browse />} />
        <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
        <Route path="/genes" element={<GeneView />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/docs" element={<Docs />} />
        <Route
          path="*"
          element={
            <div className="content">
              <h1>ページが見つかりません</h1>
              <p>
                <NavLink to="/">データセット一覧へ</NavLink>
              </p>
            </div>
          }
        />
      </Routes>
    </>
  );
}
