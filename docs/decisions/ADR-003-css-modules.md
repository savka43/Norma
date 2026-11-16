# ADR-003 — CSS Modules вместо Tailwind CSS

**Статус:** принято пользователем. **Дата:** 2026-11-15.

## Контекст

Для frontend на React + TypeScript пользователь выбрал самостоятельную разработку
UI и отказался от Tailwind CSS и shadcn/ui. Формы строятся на TanStack Form.

## Решение

- Использовать обычный CSS с локальной областью видимости через **CSS Modules**.
- Размещать `Component.module.css` рядом с `Component.tsx` внутри `features/`,
  `pages/` или `shared/ui/`.
- Импортировать стили как `styles` и применять через `className={styles.className}`.
- Держать в `app/styles/globals.css` только reset, глобальную типографику,
  переменные темы (`:root` CSS custom properties) и действительно глобальные правила.
- Повторно используемые примитивы интерфейса создавать в `shared/ui/`,
  а не копировать CSS-правила по фичам.
- Состояния (`active`, `invalid`, `disabled`) оформлять явными классами модулей.
- Не добавлять Tailwind, shadcn/ui или CSS-in-JS без отдельного согласования.

## Пример

`shared/ui/Button/Button.tsx`:

```tsx
import styles from './Button.module.css';

export function Button({ children }: { children: React.ReactNode }) {
  return <button className={styles.button}>{children}</button>;
}
```

`shared/ui/Button/Button.module.css`:

```css
.button {
  padding: 0.625rem 1rem;
  border-radius: var(--radius-md);
  background: var(--color-accent);
  color: var(--color-on-accent);
  border: 0;
}
```

## Последствия

Нет utility-first слоёв и зависимости от Tailwind. Придётся самостоятельно
определить дизайн-токены и компоненты, зато стили изолированы по модулям,
прозрачны и не требуют дополнительного стилизующего фреймворка.
