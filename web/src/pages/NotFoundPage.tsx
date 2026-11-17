import { Link } from "react-router";

import { PageTitle } from "./PageTitle";

export function NotFoundPage() {
  return (
    <section>
      <PageTitle>הדף לא נמצא</PageTitle>
      <Link to="/" className="text-blue-700 underline">
        חזרה לתור האישורים
      </Link>
    </section>
  );
}
