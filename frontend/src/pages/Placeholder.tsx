interface Props {
  title: string
  description: string
  phase: string
}

export function Placeholder({ title, description, phase }: Props) {
  return (
    <>
      <div className="page-header">
        <h1>{title}</h1>
        <p>{description}</p>
      </div>

      <div className="card">
        <div className="empty">
          Cette page arrive avec la <strong>{phase}</strong> du projet.
        </div>
      </div>
    </>
  )
}
